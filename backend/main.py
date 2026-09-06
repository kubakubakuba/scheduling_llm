import asyncio
import contextlib
import os
import json
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import Response, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from openai import AsyncOpenAI
import httpx
from dotenv import load_dotenv
import jsonschema
import traceback
import uuid
import base64
import shutil

import llm_api.toolcalls as toolcalls
import llm_api.schema as schema
from llm_api.message_utils import serialize_assistant_message
from llm_api.runtime import ToolRuntime
from llm_api.storage import ConversationStore
from analysis.manager import APPLET_CANDIDATES, APPLET_LIBRARY, AnalysisManager

MAX_HISTORY_MESSAGES = 12
MAX_MESSAGE_CHARS = 6000
MAX_TOOL_RESULT_CHARS = 12000
DEFAULT_MAX_TOOL_ROUNDS = 32
MIN_TOOL_ROUNDS = 1
MAX_TOOL_ROUNDS = 128
MAX_INVALID_TOOL_RETRIES = 1
DEFAULT_REQUEST_TIMEOUT_SECONDS = 900
MIN_REQUEST_TIMEOUT_SECONDS = 60
MAX_REQUEST_TIMEOUT_SECONDS = 3600
DEFAULT_SANDBOX_TIMEOUT_SECONDS = 600
MIN_SANDBOX_TIMEOUT_SECONDS = 60
MAX_SANDBOX_TIMEOUT_SECONDS = 3600
HEARTBEAT_INTERVAL_SECONDS = 10


class GenerationTimeout(Exception):
	"""The configured provider/tool wall time was exceeded."""


class GenerationStopped(Exception):
	"""The user requested cancellation of the current agent turn."""


@dataclass
class ActiveGeneration:
	conversation_id: str
	generation_id: str
	started_at: float
	stage: str = "starting"
	stop_requested: bool = False
	provider_task: asyncio.Task | None = None
	tool_task: asyncio.Task | None = None
	marker_persisted: bool = False


active_generations: dict[str, ActiveGeneration] = {}
active_generation_by_conversation: dict[str, str] = {}

load_dotenv(dotenv_path=Path(__file__).with_name(".env"))

app = FastAPI()
conversation_store = ConversationStore()
conversation_runtimes: dict[str, ToolRuntime] = {}
ARTIFACT_MAX_BYTES = 10_000_000


class _LibraryRuntime:
	sandbox_timeout_seconds = DEFAULT_SANDBOX_TIMEOUT_SECONDS


library_manager = AnalysisManager(_LibraryRuntime())

app.add_middleware(
	CORSMiddleware,
	allow_origins=["http://localhost:5173"],
	allow_credentials=True,
	allow_methods=["*"],
	allow_headers=["*"],
)

def compact_history(history: list[dict]) -> list[dict]:
	result = []

	for message in history:
		role = message.get("role")

		# Tool messages and assistant tool-call messages are execution traces,
		# not useful long-term conversation context.
		if role == "tool":
			continue

		if role == "assistant" and message.get("tool_calls"):
			continue

		if role not in {"user", "assistant"}:
			continue

		result.append({
			"role": role,
			"content": (message.get("content") or "")[:MAX_MESSAGE_CHARS],
		})

	return result[-MAX_HISTORY_MESSAGES:]


def compact_tool_result(function_name: str, result: dict) -> str:
	if function_name == "visualize_schedule":
		compact = {
			"status": result.get("status"),
			"visualization_type": result.get("visualization_type"),
			"weighted_tardiness": result.get("weighted_tardiness"),
			"message": (
				"The visualization was generated and displayed in the UI. "
				"The large dashboard payload is intentionally omitted from "
				"the model context."
			),
		}
		return json.dumps(compact)
	if function_name == "get_library_item_source":
		# Source is fetched explicitly and tool traces are excluded from future
		# compacted history, so preserve the exact immutable source for this round.
		return json.dumps(result, separators=(",", ":"))

	raw = json.dumps(result, separators=(",", ":"))

	if len(raw) <= MAX_TOOL_RESULT_CHARS:
		return raw

	compact = {
		"status": result.get("status"),
		"error_code": result.get("error_code"),
		"message": "Large tool output omitted from model context.",
	}

	if function_name == "run_solver":
		schedule = result.get("schedule")
		compact["has_solution"] = result.get("has_solution", False)
		compact["objective"] = result.get("objective")
		compact["weighted_tardiness"] = result.get("weighted_tardiness")
		compact["schedule_job_count"] = (
			len(schedule) if isinstance(schedule, dict) else 0
		)

	return json.dumps(compact)


def _artifact_bytes(value: str) -> str:
	return base64.b64encode(value.encode("utf-8")).decode("ascii")


def _materialize_visualization_result(conversation_id: str, function_name: str, result: dict) -> dict:
	"""Turn a compiled applet into a private conversation artifact."""
	if not isinstance(result, dict):
		return result
	public = dict(result)
	bundle_path_value = public.pop("_applet_bundle_path", None)
	context = public.pop("_applet_context", None)
	if function_name != "run_visualization_applet" or not bundle_path_value:
		return public
	bundle_path = Path(str(bundle_path_value)).resolve()
	allowed_roots = [APPLET_CANDIDATES.resolve(), APPLET_LIBRARY.resolve()]
	if bundle_path.name != "bundle.js" or not bundle_path.is_file() or not any(
		bundle_path.is_relative_to(root) for root in allowed_roots
	):
		return {"status": "error", "error_code": "applet_artifact_missing", "message": "The compiled applet artifact is missing."}
	if bundle_path.stat().st_size > ARTIFACT_MAX_BYTES:
		return {"status": "error", "error_code": "applet_artifact_too_large", "message": "The compiled applet artifact is too large to display."}
	context_json = json.dumps(context or {}, separators=(",", ":"))
	if len(context_json.encode("utf-8")) > ARTIFACT_MAX_BYTES:
		return {"status": "error", "error_code": "applet_context_too_large", "message": "The applet context is too large to display."}
	artifact_id = str(uuid.uuid4())
	artifact_dir = conversation_store.path.parent / "artifacts" / conversation_id / artifact_id
	try:
		artifact_dir.mkdir(parents=True, exist_ok=False)
		shutil.copyfile(bundle_path, artifact_dir / "bundle.js")
		(artifact_dir / "context.json").write_text(context_json, encoding="utf-8")
		conversation_store.create_artifact(
			conversation_id,
			"visualization_applet",
			artifact_dir,
			{"applet_id": public.get("applet_id"), "source_hash": public.get("source_hash"), "title": public.get("title")},
			artifact_id=artifact_id,
		)
	except Exception as exc:
		shutil.rmtree(artifact_dir, ignore_errors=True)
		return {"status": "error", "error_code": "applet_artifact_write_failed", "message": str(exc)}
	public.update({"artifact_id": artifact_id, "visualization_type": "custom_applet"})
	return public


def _applet_frame_html(bundle: str, context: dict) -> str:
	bundle_b64 = _artifact_bytes(bundle)
	context_b64 = _artifact_bytes(json.dumps(context or {}, separators=(",", ":")))
	return f'''<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none';">
<style>html,body,#root{{margin:0;min-height:100%;background:#0d0d0d;color:#e4e4e7;font-family:system-ui,sans-serif}}#root{{padding:12px;box-sizing:border-box}}</style></head>
<body><div id="root"></div><script>
(() => {{
  // Applets should append Node objects, but keep legacy candidates recoverable
  // when a helper accidentally passes a primitive label to appendChild.
  const nativeAppendChild = Node.prototype.appendChild;
  Node.prototype.appendChild = function (child) {{
    if (!(child instanceof Node)) child = document.createTextNode(String(child));
    return nativeAppendChild.call(this, child);
  }};
  const decode = (value) => decodeURIComponent(Array.from(atob(value), c => '%' + c.charCodeAt(0).toString(16).padStart(2, '0')).join(''));
  const context = JSON.parse(decode('{context_b64}'));
  const source = decode('{bundle_b64}');
  const script = document.createElement('script');
  script.textContent = source;
  document.head.appendChild(script);
  try {{
    if (!window.SchedulingApplet || typeof window.SchedulingApplet.render !== 'function') throw new Error('Applet render entry point is missing.');
    const cleanup = window.SchedulingApplet.render(document.getElementById('root'), context);
    if (typeof cleanup === 'function') window.addEventListener('unload', cleanup, {{once:true}});
    const sendSize = () => parent.postMessage({{type:'scheduling-applet-size', height:Math.min(1600, Math.max(180, document.documentElement.scrollHeight))}}, '*');
    new ResizeObserver(sendSize).observe(document.documentElement); sendSize();
  }} catch (error) {{ document.getElementById('root').textContent = 'Visualization failed: ' + (error?.message || error); parent.postMessage({{type:'scheduling-applet-error', message:String(error)}}, '*'); }}
}})();
</script></body></html>'''


def _timeout_value(value: int | None) -> int:
	if value is None:
		return DEFAULT_REQUEST_TIMEOUT_SECONDS
	return max(MIN_REQUEST_TIMEOUT_SECONDS, min(MAX_REQUEST_TIMEOUT_SECONDS, int(value)))


def _validated_timeout(value) -> int:
	if value is None:
		return DEFAULT_REQUEST_TIMEOUT_SECONDS
	try:
		result = int(value)
	except (TypeError, ValueError):
		raise HTTPException(status_code=422, detail=f"request_timeout_seconds must be an integer between {MIN_REQUEST_TIMEOUT_SECONDS} and {MAX_REQUEST_TIMEOUT_SECONDS}.")
	if not MIN_REQUEST_TIMEOUT_SECONDS <= result <= MAX_REQUEST_TIMEOUT_SECONDS:
		raise HTTPException(status_code=422, detail=f"request_timeout_seconds must be between {MIN_REQUEST_TIMEOUT_SECONDS} and {MAX_REQUEST_TIMEOUT_SECONDS} seconds.")
	return result


def _limit_value(value, *, default: int, minimum: int, maximum: int, name: str) -> int:
	if value is None:
		return default
	try:
		result = int(value)
	except (TypeError, ValueError):
		raise HTTPException(status_code=422, detail=f"{name} must be an integer between {minimum} and {maximum}.")
	if not minimum <= result <= maximum:
		raise HTTPException(status_code=422, detail=f"{name} must be between {minimum} and {maximum}.")
	return result


async def _wait_for_generation_task(
	task: asyncio.Task,
	state: ActiveGeneration,
	timeout_seconds: int,
	stage: str,
	result_holder: dict,
):
	"""Wait for a provider/tool task while yielding periodic UI status events."""
	state.stage = stage
	heartbeat_task = asyncio.create_task(asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS))
	started = time.monotonic()
	try:
		while True:
			if task.done():
				try:
					result_holder["value"] = task.result()
					return
				except asyncio.CancelledError as exc:
					if state.stop_requested:
						raise GenerationStopped from exc
					raise

			remaining = timeout_seconds - (time.monotonic() - started)
			if remaining <= 0:
				if stage != "running tool":
					await _cancel_and_drain_task(task)
				# Transactional tools are allowed to finish; the stream's finally
				# block waits for the worker and the completion callback persists its
				# committed workspace even when the provider generation timed out.
				raise GenerationTimeout

			done, _ = await asyncio.wait(
				{task, heartbeat_task},
				timeout=min(remaining, HEARTBEAT_INTERVAL_SECONDS),
				return_when=asyncio.FIRST_COMPLETED,
			)
			if task in done:
				continue
			if heartbeat_task in done:
				yield {
					"type": "status",
					"stage": "stopping" if state.stop_requested else stage,
					"elapsed_seconds": round(time.monotonic() - state.started_at, 1),
				}
				heartbeat_task = asyncio.create_task(asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS))
	finally:
		if not heartbeat_task.done():
			heartbeat_task.cancel()
			with contextlib.suppress(asyncio.CancelledError):
				await heartbeat_task


async def _cancel_and_drain_task(task: asyncio.Task | None, *, timeout_seconds: float = 5.0) -> None:
	"""Cancel a child task and consume its result before its owner is closed.

	A disconnected StreamingResponse can cancel the stream coroutine while the
	OpenAI request is still pending.  Merely calling ``task.cancel()`` leaves a
	background request which may later try to use a client that has already been
	closed, producing an unhandled ``APIConnectionError``.  Always await the
	child (with a bounded drain) so its cancellation/exception is retrieved.
	"""
	if task is None:
		return
	if not task.done():
		task.cancel()
	try:
		await asyncio.wait_for(asyncio.shield(task), timeout=timeout_seconds)
	except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
		# The exception has been retrieved by awaiting the task.  A provider
		# implementation which refuses cancellation is bounded by the timeout;
		# the done callback below still consumes a late result.
		pass

	if not task.done():
		def consume_late_result(done_task: asyncio.Task) -> None:
			with contextlib.suppress(BaseException):
				done_task.result()
		task.add_done_callback(consume_late_result)
	else:
		with contextlib.suppress(BaseException):
			task.result()


def _register_generation(conversation_id: str, generation_id: str) -> ActiveGeneration:
	if conversation_id in active_generation_by_conversation:
		raise HTTPException(status_code=409, detail="This conversation already has a generation in progress.")
	if generation_id in active_generations:
		raise HTTPException(status_code=409, detail="This generation ID is already active.")
	state = ActiveGeneration(conversation_id=conversation_id, generation_id=generation_id, started_at=time.monotonic())
	active_generations[generation_id] = state
	active_generation_by_conversation[conversation_id] = generation_id
	return state


def _unregister_generation(state: ActiveGeneration) -> None:
	active_generations.pop(state.generation_id, None)
	if active_generation_by_conversation.get(state.conversation_id) == state.generation_id:
		active_generation_by_conversation.pop(state.conversation_id, None)


TOOL_FUNCTION_SCHEMAS = {
	item["function"]["name"]: item["function"]
	for item in schema.openai_tools_schema
}


def _validation_error_details(errors) -> list[dict[str, str]]:
	details = []
	for error in sorted(errors, key=lambda item: list(item.absolute_path)):
		path = ".".join(str(part) for part in error.absolute_path) or "$"
		details.append({"path": path, "message": error.message})
	return details


def parse_and_validate_tool_arguments(function_name: str, raw_arguments: str):
	function_schema = TOOL_FUNCTION_SCHEMAS.get(function_name)
	if function_schema is None:
		return None, {
			"status": "error",
			"error_code": "unknown_tool",
			"message": f"The model requested an unknown tool: {function_name}.",
		}

	try:
		arguments = json.loads(raw_arguments)
	except (TypeError, json.JSONDecodeError) as exc:
		return None, {
			"status": "error",
			"error_code": "invalid_tool_arguments",
			"message": f"{function_name} returned invalid JSON arguments.",
			"validation_errors": [{"path": "$", "message": str(exc)}],
		}

	validator = jsonschema.Draft202012Validator(function_schema["parameters"])
	errors = list(validator.iter_errors(arguments))
	if errors:
		return None, {
			"status": "error",
			"error_code": "invalid_tool_arguments",
			"message": f"{function_name} received arguments that do not match its schema.",
			"validation_errors": _validation_error_details(errors),
		}

	return arguments, None

with open("config.toml", "rb") as f:
	config = tomllib.load(f)

class LibraryReference(BaseModel):
	kind: Literal["analysis", "visualization"]
	id: str = Field(min_length=1, max_length=240)


class LibraryVersionRequest(BaseModel):
	name: str = Field(min_length=1, max_length=160)
	description: str = Field(default="", max_length=2000)
	source: str = Field(min_length=1, max_length=500_000)


class ChatRequest(BaseModel):
	message: str
	conversation_id: str | None = None
	generation_id: str | None = None
	endpoint_uri: str = ""
	model_name: str = ""
	system_prompt: str = ""
	request_timeout_seconds: int | None = Field(default=None, ge=MIN_REQUEST_TIMEOUT_SECONDS, le=MAX_REQUEST_TIMEOUT_SECONDS)
	max_tool_rounds: int | None = Field(default=None, ge=MIN_TOOL_ROUNDS, le=MAX_TOOL_ROUNDS)
	sandbox_timeout_seconds: int | None = Field(default=None, ge=MIN_SANDBOX_TIMEOUT_SECONDS, le=MAX_SANDBOX_TIMEOUT_SECONDS)
	history: list[dict] = Field(default_factory=list)
	provider: str | None = None
	library_references: list[LibraryReference] = Field(default_factory=list, max_length=10)


def resolve_library_references(references: list[LibraryReference] | list[dict]) -> list[dict]:
	resolved: list[dict] = []
	seen: set[tuple[str, str]] = set()
	for reference in references:
		kind = reference.kind if isinstance(reference, LibraryReference) else str(reference.get("kind", ""))
		item_id = reference.id if isinstance(reference, LibraryReference) else str(reference.get("id", ""))
		key = (kind, item_id)
		if key in seen:
			continue
		seen.add(key)
		try:
			item = library_manager.library.get_item(kind, item_id, include_source=False)
		except ValueError:
			item = None
		if item is None:
			raise HTTPException(
				status_code=422,
				detail={"code": "stale_library_reference", "message": f"Library item {item_id} is no longer available."},
			)
		resolved.append({field: item.get(field) for field in ("kind", "id", "name", "description", "status", "origin", "source_hash")})
	return resolved


def message_with_library_references(message: str, references: list[dict] | None) -> str:
	if not references:
		return message
	items = "\n".join(
		f"- {item['kind']} `{item['id']}` ({item['name']}; {item['status']})"
		for item in references
	)
	return (
		f"<attached_library_items>\n{items}\n</attached_library_items>\n"
		"The attached IDs were selected explicitly by the user. Use them when relevant. "
		"Call get_library_item_source before changing an attached item; use the existing run tools to execute it.\n\n"
		f"{message}"
	)


def raise_configuration_error(
	code: str,
	message: str,
	status_code: int = 422,
	environment_variable: str | None = None,
):
	detail = {
		"code": code,
		"message": message,
	}
	if environment_variable:
		detail["environment_variable"] = environment_variable
	raise HTTPException(status_code=status_code, detail=detail)


def resolve_api_key(provider: str | None, endpoint_uri: str) -> tuple[str, str | None]:
	normalized_provider = (provider or "").lower()
	normalized_endpoint = endpoint_uri.lower()

	if (
		"lm studio" in normalized_provider
		or any(host in normalized_endpoint for host in ("localhost", "127.0.0.1", "local.ai", "host.docker.internal"))
	):
		return "lm-studio", None

	if "openrouter" in normalized_provider or "openrouter" in normalized_endpoint:
		return os.getenv("OPENROUTER_KEY", ""), "OPENROUTER_KEY"

	return os.getenv("OPENAI_API_KEY", ""), "OPENAI_API_KEY"

@app.get("/api/config")
async def get_config():
	return {
		"default_endpoint": config.get("default_endpoint", "https://openrouter.ai/api/v1"),
		"default_model": config.get("default_model", "inclusionai/ling-3.0-flash:free"),
		"default_system_prompt": config.get("default_system_prompt", "").strip(),
		"default_request_timeout_seconds": DEFAULT_REQUEST_TIMEOUT_SECONDS,
		"default_max_tool_rounds": DEFAULT_MAX_TOOL_ROUNDS,
		"default_sandbox_timeout_seconds": DEFAULT_SANDBOX_TIMEOUT_SECONDS,
		"available_models": config.get("available_models", [])
	}


@app.get("/api/library/items")
async def list_library_items(kind: str | None = None, status: str = "", query: str = ""):
	try:
		items = library_manager.library.list_items(kind=kind, status=status, query=query)
	except ValueError as exc:
		raise HTTPException(status_code=422, detail=str(exc))
	return {"items": items}


@app.get("/api/library/items/{kind}/{item_id}")
async def get_library_item(kind: str, item_id: str):
	try:
		item = library_manager.library.get_item(kind, item_id)
	except ValueError as exc:
		raise HTTPException(status_code=422, detail=str(exc))
	if item is None:
		raise HTTPException(status_code=404, detail="Library item not found.")
	return item


@app.post("/api/library/items/{kind}/{item_id}/versions")
async def create_library_item_version(kind: str, item_id: str, request: LibraryVersionRequest):
	result = await asyncio.to_thread(
		library_manager.create_library_version,
		kind,
		item_id,
		request.name,
		request.description,
		request.source,
	)
	if result.get("status") != "success":
		status_code = 404 if result.get("error_code") == "unknown_library_item" else 422
		raise HTTPException(status_code=status_code, detail=result)
	return result["item"]


@app.delete("/api/library/items/{kind}/{item_id}")
async def delete_library_item(kind: str, item_id: str):
	try:
		item = library_manager.library.delete_item(kind, item_id)
	except ValueError as exc:
		raise HTTPException(status_code=422, detail=str(exc))
	except KeyError:
		raise HTTPException(status_code=404, detail="Library item not found.")
	except PermissionError as exc:
		raise HTTPException(status_code=403, detail=str(exc))
	return {"status": "success", "deleted": {"kind": item["kind"], "id": item["id"]}}


def _conversation_runtime(conversation_id: str, conversation: dict | None = None) -> ToolRuntime:
	conversation = conversation or conversation_store.get(conversation_id)
	if conversation is None:
		raise HTTPException(status_code=404, detail="Conversation not found.")
	runtime = conversation_runtimes.get(conversation_id)
	if runtime is None:
		runtime = ToolRuntime(persistence_path=None)
		runtime.restore(conversation.get("workspace", {}))
	conversation_runtimes[conversation_id] = runtime
	return runtime


@app.get("/api/conversations")
async def list_conversations(include_trash: bool = False):
	return {"conversations": conversation_store.list(include_deleted=include_trash)}


@app.post("/api/conversations")
async def create_conversation(request: dict | None = None):
	request = request or {}
	settings = {key: request.get(key, "") for key in ("provider", "endpoint_uri", "model_name", "system_prompt") if request.get(key) is not None}
	settings["request_timeout_seconds"] = _validated_timeout(request.get("request_timeout_seconds"))
	settings["max_tool_rounds"] = _limit_value(request.get("max_tool_rounds"), default=DEFAULT_MAX_TOOL_ROUNDS, minimum=MIN_TOOL_ROUNDS, maximum=MAX_TOOL_ROUNDS, name="max_tool_rounds")
	settings["sandbox_timeout_seconds"] = _limit_value(request.get("sandbox_timeout_seconds"), default=DEFAULT_SANDBOX_TIMEOUT_SECONDS, minimum=MIN_SANDBOX_TIMEOUT_SECONDS, maximum=MAX_SANDBOX_TIMEOUT_SECONDS, name="sandbox_timeout_seconds")
	return conversation_store.create(settings=settings)


@app.get("/api/conversations/{conversation_id}")
async def get_conversation(conversation_id: str):
	conversation = conversation_store.get(conversation_id)
	if conversation is None:
		raise HTTPException(status_code=404, detail="Conversation not found.")
	return conversation


@app.get("/api/conversations/{conversation_id}/artifacts/{artifact_id}/frame")
async def get_visualization_artifact_frame(conversation_id: str, artifact_id: str):
	artifact = conversation_store.get_artifact(conversation_id, artifact_id)
	if artifact is None or artifact.get("kind") != "visualization_applet":
		raise HTTPException(status_code=404, detail="Visualization artifact not found.")
	artifact_dir = Path(artifact["path"]).resolve()
	artifact_root = (conversation_store.path.parent / "artifacts" / conversation_id).resolve()
	if not artifact_dir.is_relative_to(artifact_root):
		raise HTTPException(status_code=404, detail="Visualization artifact not found.")
	bundle_path = artifact_dir / "bundle.js"
	context_path = artifact_dir / "context.json"
	if not bundle_path.is_file() or not context_path.is_file():
		raise HTTPException(status_code=404, detail="Visualization artifact files are unavailable.")
	if bundle_path.stat().st_size > ARTIFACT_MAX_BYTES or context_path.stat().st_size > ARTIFACT_MAX_BYTES:
		raise HTTPException(status_code=413, detail="Visualization artifact is too large to render.")
	try:
		bundle = bundle_path.read_text(encoding="utf-8")
		context = json.loads(context_path.read_text(encoding="utf-8"))
	except (OSError, json.JSONDecodeError) as exc:
		raise HTTPException(status_code=500, detail=f"Visualization artifact could not be loaded: {exc}")
	return Response(
		_applet_frame_html(bundle, context),
		media_type="text/html",
		headers={
			"Content-Security-Policy": "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors http://localhost:5173 http://127.0.0.1:5173 http://local.ai:5173",
			"X-Content-Type-Options": "nosniff",
			"Referrer-Policy": "no-referrer",
		},
	)


@app.patch("/api/conversations/{conversation_id}")
async def update_conversation(conversation_id: str, request: dict):
	if conversation_store.get(conversation_id, include_deleted=True) is None:
		raise HTTPException(status_code=404, detail="Conversation not found.")
	settings = request.get("settings")
	if isinstance(settings, dict) and "request_timeout_seconds" in settings:
		settings = dict(settings)
		settings["request_timeout_seconds"] = _validated_timeout(settings.get("request_timeout_seconds"))
	if isinstance(settings, dict) and "max_tool_rounds" in settings:
		settings = dict(settings)
		settings["max_tool_rounds"] = _limit_value(settings.get("max_tool_rounds"), default=DEFAULT_MAX_TOOL_ROUNDS, minimum=MIN_TOOL_ROUNDS, maximum=MAX_TOOL_ROUNDS, name="max_tool_rounds")
	if isinstance(settings, dict) and "sandbox_timeout_seconds" in settings:
		settings = dict(settings)
		settings["sandbox_timeout_seconds"] = _limit_value(settings.get("sandbox_timeout_seconds"), default=DEFAULT_SANDBOX_TIMEOUT_SECONDS, minimum=MIN_SANDBOX_TIMEOUT_SECONDS, maximum=MAX_SANDBOX_TIMEOUT_SECONDS, name="sandbox_timeout_seconds")
	conversation_store.update(conversation_id, title=request.get("title"), pinned=request.get("pinned"), settings=settings)
	return conversation_store.get(conversation_id, include_deleted=True)


@app.delete("/api/conversations/{conversation_id}")
async def trash_conversation(conversation_id: str):
	conversation_store.trash(conversation_id)
	return {"status": "trashed"}


@app.post("/api/conversations/{conversation_id}/restore")
async def restore_conversation(conversation_id: str):
	conversation_store.restore(conversation_id)
	return {"status": "restored"}


@app.delete("/api/conversations/{conversation_id}/purge")
async def purge_conversation(conversation_id: str):
	conversation_store.purge(conversation_id)
	conversation_runtimes.pop(conversation_id, None)
	return {"status": "purged"}

@app.post("/api/upload")
async def upload_instance(file: UploadFile = File(...), conversation_id: str | None = None):
	if not file.filename.endswith('.json'):
		raise HTTPException(status_code=400, detail="Only JSON files are allowed.")

	content = await file.read()
	try:
		instance_data = json.loads(content)
	except json.JSONDecodeError:
		raise HTTPException(
			status_code=400,
			detail="Invalid JSON file structure."
		)

	if not conversation_id:
		conversation = conversation_store.create()
		conversation_id = conversation["id"]
	conversation = conversation_store.get(conversation_id)
	runtime = _conversation_runtime(conversation_id, conversation)
	load_result = runtime.load_instance(instance_data)

	if load_result["status"] != "success":
		raise HTTPException(
			status_code=422,
			detail=load_result
		)

	conversation_store.save_workspace(conversation_id, runtime.snapshot())
	return {
		"message": f"Successfully loaded {file.filename}",
		"revision": load_result["revision"],
		"conversation_id": conversation_id,
	}


@app.post("/api/conversations/{conversation_id}/generations/{generation_id}/stop")
async def stop_generation(conversation_id: str, generation_id: str):
	generation = active_generations.get(generation_id)
	if generation is None or generation.conversation_id != conversation_id:
		return {
			"status": "not_found",
			"stopped": False,
			"generation_id": generation_id,
		}

	generation.stop_requested = True
	generation.stage = "stopping"
	provider_active = generation.provider_task is not None and not generation.provider_task.done()
	tool_active = generation.tool_task is not None and not generation.tool_task.done()
	if provider_active:
		# Cancelling the asyncio task closes the underlying httpx request, which
		# causes OpenAI-compatible servers such as llama.cpp to stop generation.
		generation.provider_task.cancel()
	return {
		"status": "stopping",
		"stopped": True,
		"generation_id": generation_id,
		"immediate": provider_active or not tool_active,
		"in_flight_tool": tool_active,
	}

@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
	resolved_library_references = resolve_library_references(request.library_references)
	conversation = conversation_store.get(request.conversation_id) if request.conversation_id else None
	if conversation is None:
		conversation = conversation_store.create({
			"provider": request.provider or "",
			"endpoint_uri": request.endpoint_uri,
			"model_name": request.model_name,
			"system_prompt": request.system_prompt,
			"request_timeout_seconds": _timeout_value(request.request_timeout_seconds),
			"max_tool_rounds": _limit_value(request.max_tool_rounds, default=DEFAULT_MAX_TOOL_ROUNDS, minimum=MIN_TOOL_ROUNDS, maximum=MAX_TOOL_ROUNDS, name="max_tool_rounds"),
			"sandbox_timeout_seconds": _limit_value(request.sandbox_timeout_seconds, default=DEFAULT_SANDBOX_TIMEOUT_SECONDS, minimum=MIN_SANDBOX_TIMEOUT_SECONDS, maximum=MAX_SANDBOX_TIMEOUT_SECONDS, name="sandbox_timeout_seconds"),
		})
	conversation_id = conversation["id"]
	runtime = _conversation_runtime(conversation_id, conversation)
	settings = conversation.get("settings", {})
	# Avoid accepting a second turn for the same conversation.  The registry
	# check is repeated immediately before streaming to cover races.
	if conversation_id in active_generation_by_conversation:
		raise HTTPException(status_code=409, detail="This conversation already has a generation in progress.")
	if request.endpoint_uri:
		settings.update({
			"provider": request.provider or settings.get("provider", ""),
			"endpoint_uri": request.endpoint_uri,
			"model_name": request.model_name,
			"system_prompt": request.system_prompt,
		})
	else:
		request.endpoint_uri = settings.get("endpoint_uri", "")
		request.model_name = settings.get("model_name", "")
		request.system_prompt = settings.get("system_prompt", "")
		request.provider = settings.get("provider")
	request_timeout_seconds = _timeout_value(
		request.request_timeout_seconds
		if request.request_timeout_seconds is not None
		else settings.get("request_timeout_seconds", DEFAULT_REQUEST_TIMEOUT_SECONDS)
	)
	settings["request_timeout_seconds"] = request_timeout_seconds
	max_tool_rounds = _limit_value(
		request.max_tool_rounds if request.max_tool_rounds is not None else settings.get("max_tool_rounds"),
		default=DEFAULT_MAX_TOOL_ROUNDS,
		minimum=MIN_TOOL_ROUNDS,
		maximum=MAX_TOOL_ROUNDS,
		name="max_tool_rounds",
	)
	sandbox_timeout_seconds = _limit_value(
		request.sandbox_timeout_seconds if request.sandbox_timeout_seconds is not None else settings.get("sandbox_timeout_seconds"),
		default=DEFAULT_SANDBOX_TIMEOUT_SECONDS,
		minimum=MIN_SANDBOX_TIMEOUT_SECONDS,
		maximum=MAX_SANDBOX_TIMEOUT_SECONDS,
		name="sandbox_timeout_seconds",
	)
	settings["max_tool_rounds"] = max_tool_rounds
	settings["sandbox_timeout_seconds"] = sandbox_timeout_seconds
	conversation_store.update(conversation_id, settings=settings)
	runtime.set_sandbox_timeout(sandbox_timeout_seconds)
	stored_messages = conversation.get("messages", [])
	stored_history = [
		{
			"role": message["role"],
			"content": message_with_library_references(message.get("content", ""), message.get("library_references"))
			if message.get("role") == "user"
			else message.get("content", ""),
		}
		for message in stored_messages
		if message.get("role") in {"user", "assistant"}
		and not message.get("tool_calls")
		and not message.get("incomplete")
	]
	if not stored_history and request.history:
		stored_history = request.history
	conversation_store.append_message(
		conversation_id,
		"user",
		request.message,
		{"library_references": resolved_library_references} if resolved_library_references else None,
	)
	base_url = request.endpoint_uri.strip().rstrip("/")
	model_name = request.model_name.strip()

	if not base_url:
		raise_configuration_error(
			"missing_endpoint",
			"No model endpoint is configured. Open the settings panel and choose an endpoint.",
		)
	if not model_name:
		raise_configuration_error(
			"missing_model",
			"No model is configured. Open the settings panel and choose a model.",
		)

	parsed_endpoint = urlparse(base_url)
	if parsed_endpoint.scheme not in {"http", "https"} or not parsed_endpoint.netloc:
		raise_configuration_error(
			"invalid_endpoint",
			"The configured model endpoint must be a complete HTTP or HTTPS URL.",
		)

	api_key, environment_variable = resolve_api_key(request.provider, base_url)
	if not api_key:
		raise_configuration_error(
			"missing_api_key",
			(
				f"The selected provider is missing its server-side API key. "
				f"Set {environment_variable} in backend/.env and restart the backend."
			),
			status_code=503,
			environment_variable=environment_variable,
		)

	try:
		client = AsyncOpenAI(
			base_url=base_url,
			api_key=api_key,
			timeout=httpx.Timeout(
				connect=15.0,
				read=float(request_timeout_seconds),
				write=30.0,
				pool=15.0,
			),
		)
	except Exception:
		raise_configuration_error(
			"client_initialization_failed",
			"The configured model client could not be initialized. Check the endpoint and provider settings.",
			status_code=503,
		)

	clean_history = compact_history(stored_history)
	generation_id = (request.generation_id or str(uuid.uuid4())).strip() or str(uuid.uuid4())
	try:
		generation = _register_generation(conversation_id, generation_id)
	except HTTPException:
		await client.close()
		raise

	async def stream_generator():
		messages = [{"role": "system", "content": request.system_prompt}] + clean_history
		messages.append({"role": "user", "content": message_with_library_references(request.message, resolved_library_references)})
		tool_rounds = 0
		invalid_argument_retries = 0
		completed = False

		def persist_incomplete(status: str, content: str, detail: str | None = None):
			if generation.marker_persisted or completed:
				return
			payload = {
				"generation_id": generation.generation_id,
				"incomplete": True,
				"status": status,
				"stage": generation.stage,
			}
			if detail:
				payload["error"] = detail
			conversation_store.append_message(conversation_id, "assistant", content, payload)
			generation.marker_persisted = True

		def status_line(stage: str) -> str:
			generation.stage = stage
			return json.dumps({
				"type": "status",
				"stage": stage,
				"elapsed_seconds": round(time.monotonic() - generation.started_at, 1),
			}) + "\n"

		try:
			while tool_rounds < max_tool_rounds:
				if generation.stop_requested:
					raise GenerationStopped

				provider_holder: dict[str, object] = {}
				yield status_line("thinking")
				provider_task = asyncio.create_task(client.chat.completions.create(
					model=model_name,
					messages=messages,
					tools=schema.openai_tools_schema,
				))
				generation.provider_task = provider_task
				try:
					async for status_event in _wait_for_generation_task(
						provider_task,
						generation,
						request_timeout_seconds,
						"thinking",
						provider_holder,
					):
						yield json.dumps(status_event) + "\n"
					response = provider_holder["value"]
				finally:
					# Keep a pending provider task visible to the outer cleanup block
					# when the browser disconnects and cancels this stream.
					if provider_task.done():
						await _cancel_and_drain_task(provider_task)
						if generation.provider_task is provider_task:
							generation.provider_task = None

				if generation.stop_requested:
					raise GenerationStopped

				response_message = response.choices[0].message

				if response_message.tool_calls:
					tool_rounds += 1
					assistant_msg = serialize_assistant_message(response_message)
					messages.append(assistant_msg)
					conversation_store.append_message(conversation_id, "assistant", assistant_msg.get("content", ""), {"tool_calls": assistant_msg.get("tool_calls", [])})

					yield json.dumps({"type": "message", "data": assistant_msg}) + "\n"

					for tool_call in response_message.tool_calls:
						func_name = tool_call.function.name
						if generation.stop_requested:
							result = {
								"status": "cancelled",
								"error_code": "generation_stopped",
								"message": "The tool was not started because the generation was stopped.",
							}
							validation_result = None
							args = {}
							tool_cancelled = True
						else:
							args, validation_result = parse_and_validate_tool_arguments(
								func_name,
								tool_call.function.arguments,
							)
							tool_cancelled = False

						if tool_cancelled:
							stop_after_tool = True
						elif validation_result:
							result = validation_result
							if result.get("error_code") == "invalid_tool_arguments":
								invalid_argument_retries += 1
						else:
							yield status_line("running tool")
							def invoke_tool_safely(tool_name=func_name, tool_args=args):
								try:
									return runtime.invoke(tool_name, tool_args)
								except Exception as exc:
									return {
										"status": "error",
										"error_code": "tool_execution_failed",
										"message": str(exc),
									}
							generation.tool_task = asyncio.create_task(asyncio.to_thread(invoke_tool_safely))
							def persist_finished_tool(task: asyncio.Task):
								# A browser disconnect can cancel the stream while the worker
								# thread is still finishing. Persist its committed runtime state
								# independently so successful mutations remain recoverable.
								if task.cancelled():
									return
								try:
									task.result()
								except BaseException:
									return
								try:
									conversation_store.save_workspace(conversation_id, runtime.snapshot())
								except Exception:
									pass
							generation.tool_task.add_done_callback(persist_finished_tool)
							tool_holder: dict[str, object] = {}
							current_tool_task = generation.tool_task
							try:
								async for status_event in _wait_for_generation_task(
									generation.tool_task,
									generation,
									request_timeout_seconds,
									"running tool",
									tool_holder,
								):
									yield json.dumps(status_event) + "\n"
								result = tool_holder["value"]
							finally:
								if current_tool_task is None or current_tool_task.done():
									generation.tool_task = None

							if not isinstance(result, dict):
								result = {"status": "success", "result": result}
							result = _materialize_visualization_result(conversation_id, func_name, result)
							if generation.stop_requested:
								# The tool result is retained; no subsequent tool/model round
								# is started after this point.
								stop_after_tool = True
							else:
								stop_after_tool = False
						conversation_store.save_workspace(conversation_id, runtime.snapshot())

						#full result to frontend
						ui_tool_msg = {
							"role": "tool",
							"tool_call_id": tool_call.id,
							"name": func_name,
							"content": json.dumps(result),
						}

						#compact res back to model
						model_tool_msg = {
							"role": "tool",
							"tool_call_id": tool_call.id,
							"name": func_name,
							"content": compact_tool_result(func_name, result),
						}

						#compact result back to msg hist
						messages.append(model_tool_msg)

						#frontend response
						conversation_store.append_message(conversation_id, "tool", ui_tool_msg["content"], {"tool_call_id": tool_call.id, "name": func_name})
						yield json.dumps({
							"type": "message",
							"data": ui_tool_msg,
						}) + "\n"
						# Continue through the remaining tool calls only to emit explicit
						# cancelled results for their cards. No further tool or model work
						# is started once the stop flag is set.

					if generation.stop_requested:
						raise GenerationStopped

					if invalid_argument_retries > MAX_INVALID_TOOL_RETRIES:
						message = (
							"The model repeatedly sent invalid tool arguments. "
							"The request was stopped without changing the instance."
						)
						persist_incomplete("error", message)
						yield json.dumps({"type": "error", "detail": message}) + "\n"
						break
				else:
					reasoning = getattr(response_message, "reasoning_content", None)
					if not reasoning and hasattr(response_message, "model_extra") and response_message.model_extra:
						reasoning = response_message.model_extra.get("reasoning_content")

					final_msg = {
						"role": "assistant",
						"content": response_message.content or "",
						"reasoning": reasoning
					}

					# final response
					conversation_store.append_message(conversation_id, "assistant", final_msg["content"], {"reasoning": reasoning})
					completed = True
					yield json.dumps({"type": "message", "data": final_msg}) + "\n"
					break
			else:
				# The tool budget limits autonomous work, but it should not turn a
				# successfully completed solve into a generic failure. Ask once for a
				# text-only summary of the results already collected.
				yield status_line("finalizing")
				finalization_messages = messages + [{
					"role": "system",
					"content": (
						f"The configured budget of {max_tool_rounds} tool rounds has been reached. "
						"Do not request tools. Provide a concise final answer using the tool results "
						"already available, state what was completed, and clearly identify anything "
						"that remains unresolved."
					),
				}]
				finalization_holder: dict[str, object] = {}
				finalization_task = asyncio.create_task(client.chat.completions.create(
					model=model_name,
					messages=finalization_messages,
				))
				generation.provider_task = finalization_task
				try:
					async for status_event in _wait_for_generation_task(
						finalization_task,
						generation,
						request_timeout_seconds,
						"finalizing",
						finalization_holder,
					):
						yield json.dumps(status_event) + "\n"
					final_response = finalization_holder["value"]
					final_response_message = final_response.choices[0].message
					if final_response_message.tool_calls:
						raise RuntimeError("The model requested another tool during finalization.")
					final_msg = {
						"role": "assistant",
						"content": final_response_message.content or "",
						"reasoning": getattr(final_response_message, "reasoning_content", None),
					}
					conversation_store.append_message(conversation_id, "assistant", final_msg["content"], {"reasoning": final_msg["reasoning"]})
					completed = True
					yield json.dumps({"type": "message", "data": final_msg}) + "\n"
				except (GenerationStopped, GenerationTimeout):
					raise
				except Exception as exc:
					message = f"The model could not finalize after {max_tool_rounds} tool rounds."
					persist_incomplete("error", message, str(exc))
					yield json.dumps({"type": "error", "detail": str(exc), "error_code": "tool_round_finalization_failed"}) + "\n"
				finally:
					if finalization_task.done():
						await _cancel_and_drain_task(finalization_task)
						if generation.provider_task is finalization_task:
							generation.provider_task = None
		except GenerationStopped:
			message = "Generation stopped by user."
			persist_incomplete("cancelled", message)
			yield json.dumps({"type": "cancelled", "detail": message, "generation_id": generation.generation_id}) + "\n"
		except GenerationTimeout:
			message = f"The model request exceeded the {request_timeout_seconds}-second timeout."
			persist_incomplete("timeout", message)
			yield json.dumps({"type": "error", "detail": message, "error_code": "generation_timeout"}) + "\n"
		except asyncio.CancelledError:
			# A disconnected browser cancels the response task. Preserve the
			# incomplete attempt, then re-raise so ASGI can finish disconnecting.
			persist_incomplete("cancelled", "Generation interrupted.")
			raise
		except Exception as exc:
			traceback.print_exc()
			persist_incomplete("error", "The model request failed.", str(exc))
			yield json.dumps({"type": "error", "detail": str(exc)}) + "\n"
		finally:
			# Drain the provider before closing its HTTP client. This is essential
			# for disconnects: otherwise the SDK task can wake up afterward and
			# attempt another request on a closed httpx client.
			provider_task = generation.provider_task
			if provider_task is not None:
				await _cancel_and_drain_task(provider_task)
				if generation.provider_task is provider_task:
					generation.provider_task = None
			if generation.tool_task and not generation.tool_task.done():
				# Do not abandon a transactional tool thread. It will finish under
				# the ToolRuntime lock even if the client disconnected.
				with contextlib.suppress(BaseException):
					await asyncio.shield(generation.tool_task)
			try:
				await client.close()
			except Exception:
				# Closing an already-failed provider client must not strand the
				# conversation in the active-generation registry.
				pass
			finally:
				_unregister_generation(generation)

	return StreamingResponse(
		stream_generator(),
		media_type="application/x-ndjson",
		headers={"X-Generation-ID": generation_id, "Cache-Control": "no-cache"},
	)

if __name__ == "__main__":
	import uvicorn
	uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
