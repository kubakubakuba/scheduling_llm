import os
import json
import tomllib
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import AsyncOpenAI
from dotenv import load_dotenv
import traceback

import llm_api.toolcalls as toolcalls
import llm_api.schema as schema

MAX_HISTORY_MESSAGES = 12
MAX_MESSAGE_CHARS = 6000
MAX_TOOL_RESULT_CHARS = 12000

load_dotenv()

app = FastAPI()

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

with open("config.toml", "rb") as f:
	config = tomllib.load(f)

class ChatRequest(BaseModel):
	message: str
	endpoint_uri: str
	model_name: str
	system_prompt: str
	history: list[dict]

@app.get("/api/config")
async def get_config():
	return {
		"default_endpoint": config.get("default_endpoint", "https://openrouter.ai/api/v1"),
		"default_model": config.get("default_model", "inclusionai/ling-3.0-flash:free"),
		"default_system_prompt": config.get("default_system_prompt", "").strip(),
		"available_models": config.get("available_models", [])
	}

@app.post("/api/upload")
async def upload_instance(file: UploadFile = File(...)):
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

	load_result = toolcalls.load_instance_data(instance_data)

	if load_result["status"] != "success":
		raise HTTPException(
			status_code=422,
			detail=load_result
		)

	return {
		"message": f"Successfully loaded {file.filename}",
		"revision": load_result["revision"],
	}

@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
	base_url = request.endpoint_uri
	if "localhost" in base_url or "127.0.0.1" in base_url:
		api_key = "lm-studio"
	elif "openrouter" in base_url:
		api_key = os.getenv("OPENROUTER_KEY")
	else:
		api_key = os.getenv("OPENAI_API_KEY")

	client = AsyncOpenAI(base_url=base_url, api_key=api_key)

	clean_history = compact_history(request.history)

	async def stream_generator():
		messages = [{"role": "system", "content": request.system_prompt}] + clean_history
		messages.append({"role": "user", "content": request.message})

		while True:
			try:
				response = await client.chat.completions.create(
					model=request.model_name,
					messages=messages,
					tools=schema.openai_tools_schema
				)

				response_message = response.choices[0].message

				if response_message.tool_calls:
					assistant_msg = {
						"role": "assistant",
						"content": response_message.content or "",
						"tool_calls": [
							{
								"id": tc.id,
								"type": tc.type,
								"function": {
									"name": tc.function.name,
									"arguments": tc.function.arguments
								}
							} for tc in response_message.tool_calls
						]
					}
					messages.append(assistant_msg)

					yield json.dumps({"type": "message", "data": assistant_msg}) + "\n"

					for tool_call in response_message.tool_calls:
						func_name = tool_call.function.name
						try:
							args = json.loads(tool_call.function.arguments)
						except json.JSONDecodeError:
							args = {}

						if hasattr(toolcalls, func_name):
							func = getattr(toolcalls, func_name)
							result = func(**args)
						else:
							result = {
								"status": "error",
								"error": f"Unknown tool {func_name}"
							}

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
						yield json.dumps({
							"type": "message",
							"data": ui_tool_msg,
						}) + "\n"
				else:
					reasoning = getattr(response_message, "reasoning_content", None)
					if not reasoning and hasattr(response_message, "model_extra") and response_message.model_extra:
						reasoning = response_message.model_extra.get("reasoning_content")

					final_msg = {
						"role": "assistant",
						"content": response_message.content or "",
						"reasoning": reasoning
					}

					#final response
					yield json.dumps({"type": "message", "data": final_msg}) + "\n"
					break

			except Exception as e:
				traceback.print_exc()
				yield json.dumps({"type": "error", "detail": str(e)}) + "\n"
				break

	return StreamingResponse(stream_generator(), media_type="application/x-ndjson")

if __name__ == "__main__":
	import uvicorn
	uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
