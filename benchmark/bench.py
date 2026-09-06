#!/usr/bin/env python3
"""Run reproducible LLM evaluations against the project's real scheduling tools."""

from __future__ import annotations

import copy
import csv
import hashlib
import json
import os
import platform
import re
import sys
import time
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any

import jsonschema
import typer
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from llm_api import schema as llm_schema
from llm_api.message_utils import serialize_assistant_message as _shared_serialize_assistant_message
from llm_api.runtime import ToolRuntime
from llm_api.schema_validator import validate_instance


app = typer.Typer(help="Benchmark OpenAI-compatible LLMs on scheduling tasks.")
TOOL_SCHEMAS = {
    item["function"]["name"]: item["function"]
    for item in llm_schema.openai_tools_schema
}
MUTATION_TOOLS = {
    "edit_json_in_place",
    "propose_updated_instance",
    "set_order_due_date",
    "set_job_duration",
    "set_resource_capacity",
    "add_precedence_constraint",
    "remove_precedence_constraint",
}
MAX_HISTORY_MESSAGES = 12
MAX_MESSAGE_CHARS = 6000
MAX_TOOL_RESULT_CHARS = 12000
MAX_TOOL_ROUNDS = 16
MAX_INVALID_TOOL_RETRIES = 1
INFRASTRUCTURE_ERROR_TYPES = {
    "APIConnectionError",
    "APITimeoutError",
    "ConnectError",
    "ConnectionError",
    "TimeoutError",
}


def _json(value: Any) -> Any:
    """Convert SDK objects and solver values into trace-safe JSON values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(v) for v in value]
    if hasattr(value, "model_dump"):
        return _json(value.model_dump())
    if hasattr(value, "__dict__"):
        return _json(vars(value))
    return str(value)


def _serialize_assistant_message(message: Any) -> dict:
    """Serialize a provider response without dropping provider extensions.

    Gemini's OpenAI-compatible endpoint attaches thought signatures to tool
    calls.  Rebuilding a tool call from only ``id/type/function`` loses that
    signature and makes the next request fail with a protocol error.  The SDK
    model dump includes both declared fields and ``model_extra`` fields, so it
    is the safest wire representation to replay.
    """
    return _shared_serialize_assistant_message(message)


def _is_infrastructure_error(error: dict) -> bool:
    error_type = str(error.get("type", ""))
    message = str(error.get("message", "")).lower()
    return (
        error_type in INFRASTRUCTURE_ERROR_TYPES
        or "connection error" in message
        or "connection attempts failed" in message
        or "timed out" in message
    )


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _compact_history(history: list[dict]) -> list[dict]:
    result = []
    for message in history:
        role = message.get("role")
        if role not in {"user", "assistant"} or message.get("tool_calls"):
            continue
        result.append({"role": role, "content": (message.get("content") or "")[:MAX_MESSAGE_CHARS]})
    return result[-MAX_HISTORY_MESSAGES:]


def _compact_tool_result(name: str, result: dict) -> str:
    raw = json.dumps(_json(result), separators=(",", ":"))
    if len(raw) <= MAX_TOOL_RESULT_CHARS:
        return raw
    compact = {
        "status": result.get("status"),
        "error_code": result.get("error_code"),
        "message": "Large tool output omitted from model context.",
    }
    if name == "run_solver":
        schedule = result.get("schedule")
        compact.update({
            "has_solution": result.get("has_solution", False),
            "objective": result.get("objective"),
            "weighted_tardiness": result.get("weighted_tardiness"),
            "schedule_job_count": len(schedule) if isinstance(schedule, dict) else 0,
        })
    return json.dumps(compact)


def _validate_tool_args(name: str, raw: str) -> tuple[dict | None, dict | None]:
    function_schema = TOOL_SCHEMAS.get(name)
    if function_schema is None:
        return None, {"status": "error", "error_code": "unknown_tool", "message": f"Unknown tool: {name}."}
    try:
        arguments = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        return None, {
            "status": "error", "error_code": "invalid_tool_arguments",
            "message": f"{name} returned invalid JSON arguments.",
            "validation_errors": [{"path": "$", "message": str(exc)}],
        }
    errors = list(jsonschema.Draft202012Validator(function_schema["parameters"]).iter_errors(arguments))
    if errors:
        return None, {
            "status": "error", "error_code": "invalid_tool_arguments",
            "message": f"{name} received invalid arguments.",
            "validation_errors": [{"path": ".".join(map(str, e.absolute_path)) or "$", "message": e.message} for e in errors],
        }
    return arguments, None


def load_config(config_path: str | Path) -> tuple[dict, Path]:
    path = Path(config_path).expanduser().resolve()
    with path.open("rb") as handle:
        config = tomllib.load(handle)
    base = path.parent
    if not isinstance(config.get("run"), dict):
        raise ValueError("[run] is required")
    resolved_prompts = {}
    prompts = config.get("system_prompts")
    if not isinstance(prompts, list) or not prompts:
        raise ValueError("system_prompts must be an array of tables")
    for entry in prompts:
        if not isinstance(entry, dict):
            raise ValueError("Each [[system_prompts]] entry must be a table")
        prompt_name = entry.get("name")
        if not isinstance(prompt_name, str) or not prompt_name.strip():
            raise ValueError("Each [[system_prompts]] entry requires a non-empty name")
        has_text = "txt" in entry
        has_file = "file" in entry
        if has_text == has_file:
            raise ValueError(f"System prompt {prompt_name!r} must define exactly one of txt or file")
        prompt_value = entry["txt"] if has_text else {"file": entry["file"]}
        if prompt_name in resolved_prompts:
            raise ValueError(f"Duplicate system prompt name: {prompt_name}")
        if isinstance(prompt_value, str):
            resolved_prompts[prompt_name] = prompt_value
            continue
        if isinstance(prompt_value, dict) and isinstance(prompt_value.get("file"), str):
            prompt_path = base / prompt_value["file"]
            if not prompt_path.is_file():
                raise ValueError(f"System prompt file does not exist: {prompt_path}")
            resolved_prompts[prompt_name] = prompt_path.read_text(encoding="utf-8")
            continue
        raise ValueError(f"System prompt {prompt_name!r} must contain string txt or file")
    profiles = config.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        raise ValueError("At least one [[profiles]] entry is required")
    profile_ids = set()
    for profile in profiles:
        pid = profile.get("id")
        if not pid or pid in profile_ids:
            raise ValueError(f"Profiles must have unique non-empty ids: {pid!r}")
        profile_ids.add(pid)
        prompt_name = profile.get("system_prompt")
        if prompt_name not in resolved_prompts:
            raise ValueError(f"Profile {pid} references unknown system prompt {prompt_name!r}")
        if not profile.get("endpoint") or not profile.get("model"):
            raise ValueError(f"Profile {pid} requires endpoint and model")
    suites = config.get("suites")
    if not isinstance(suites, list) or not suites:
        raise ValueError("At least one [[suites]] entry is required")
    suite_ids = set()
    for suite in suites:
        sid = suite.get("id")
        if not sid or sid in suite_ids:
            raise ValueError(f"Suites must have unique non-empty ids: {sid!r}")
        suite_ids.add(sid)
        if suite.get("mode", "isolated") not in {"isolated", "cumulative"}:
            raise ValueError(f"Suite {sid} mode must be isolated or cumulative")
        instance_path = base / suite.get("instance", "")
        if not instance_path.is_file():
            raise ValueError(f"Suite {sid} instance does not exist: {instance_path}")
        cases = suite.get("cases")
        if not isinstance(cases, list) or not cases:
            raise ValueError(f"Suite {sid} requires at least one [[suites.cases]] entry")
        case_ids = set()
        for case in cases:
            cid = case.get("id")
            if not cid or cid in case_ids:
                raise ValueError(f"Suite {sid} cases must have unique ids")
            case_ids.add(cid)
            prompts_value = case.get("prompts")
            if not isinstance(prompts_value, list) or not all(isinstance(p, str) and p.strip() for p in prompts_value):
                raise ValueError(f"Case {sid}/{cid} requires a non-empty prompts array")
            if case.get("reference_actions") is not None and case.get("reference_instance") is not None:
                raise ValueError(f"Case {sid}/{cid} cannot define both reference_actions and reference_instance")
            if case.get("reference_instance"):
                reference_path = base / case["reference_instance"]
                if not reference_path.is_file():
                    raise ValueError(f"Reference does not exist: {reference_path}")
            actions = case.get("reference_actions", [])
            if not isinstance(actions, list):
                raise ValueError(f"reference_actions must be an array in {sid}/{cid}")
            for action in actions:
                if not isinstance(action, dict):
                    raise ValueError(f"Each reference action must be a table in {sid}/{cid}")
                if action.get("tool") not in MUTATION_TOOLS:
                    raise ValueError(f"Unsupported reference action tool: {action.get('tool')}")
                if not isinstance(action.get("arguments", {}), dict):
                    raise ValueError(f"Reference action arguments must be a table in {sid}/{cid}")
            required_tools = case.get("required_tools", {})
            if not isinstance(required_tools, (dict, list)):
                raise ValueError(f"required_tools must be a table or array in {sid}/{cid}")
            if case.get("tool_expectations", "diagnostic") not in {"diagnostic", "hard"}:
                raise ValueError(f"Case {sid}/{cid} tool_expectations must be diagnostic or hard")
            patterns = case.get("response_patterns", [])
            if not isinstance(patterns, list) or not all(isinstance(pattern, str) for pattern in patterns):
                raise ValueError(f"response_patterns must be an array of strings in {sid}/{cid}")
    config["_base_dir"] = str(base)
    config["_resolved_profile_prompts"] = {
        profile["id"]: resolved_prompts[profile["system_prompt"]]
        for profile in profiles
    }
    return config, path


def _canonical_instance(instance: dict) -> dict:
    value = copy.deepcopy(instance)
    value["jobs"] = sorted(value["jobs"])
    value["resources"] = sorted(value["resources"])
    value["durations"] = {k: value["durations"][k] for k in sorted(value["durations"], key=int)}
    value["predecessors"] = {k: sorted(value["predecessors"][k]) for k in sorted(value["predecessors"], key=int)}
    value["requests"] = sorted(value["requests"], key=lambda r: (r["job"], r["resource"]))
    value["shifts"] = {k: sorted(value["shifts"][k]) for k in sorted(value["shifts"])}
    value["orders"] = sorted(value["orders"], key=lambda o: o["sink_job"])
    return value


def _reference_for_case(case: dict, base: Path, runtime: ToolRuntime) -> tuple[dict, list[dict]]:
    actions = []
    if case.get("reference_instance"):
        instance = _read_json(base / case["reference_instance"])
        result = runtime.load_instance(instance)
        if result.get("status") != "success":
            raise ValueError(f"Reference instance is invalid: {result}")
        return instance, actions
    for action in case.get("reference_actions", []):
        name = action["tool"]
        arguments = action.get("arguments", {})
        result = runtime.invoke(name, arguments)
        actions.append({"tool": name, "arguments": arguments, "result": _json(result)})
        if result.get("status") not in {"success", "committed"}:
            raise ValueError(f"Reference action {name} failed: {result}")
    return runtime.instance, actions


def validate_schedule(instance: dict, schedule: dict | None) -> dict:
    errors: list[str] = []
    if not isinstance(schedule, dict):
        return {"valid": False, "errors": ["No schedule was returned."], "objective": None}
    normalized = {}
    for key, value in schedule.items():
        try:
            normalized[int(key)] = tuple(value)
        except (TypeError, ValueError):
            errors.append(f"Invalid schedule entry for job {key}.")
    jobs = {int(j) for j in instance["jobs"]}
    if set(normalized) != jobs:
        errors.append(f"Schedule jobs differ from instance: missing={sorted(jobs - set(normalized))}, extra={sorted(set(normalized) - jobs)}")
    for job in jobs & set(normalized):
        times = normalized[job]
        if len(times) != 2 or not all(isinstance(v, int) for v in times):
            errors.append(f"Job {job} must have integer [start, end].")
            continue
        start, end = times
        if start < 0 or end < start:
            errors.append(f"Job {job} has invalid interval [{start}, {end}).")
        if end - start != instance["durations"][str(job)]:
            errors.append(f"Job {job} duration does not match the instance.")
    for after, predecessors in instance["predecessors"].items():
        if int(after) not in normalized:
            continue
        for before in predecessors:
            if int(before) in normalized and normalized[int(before)][1] > normalized[int(after)][0]:
                errors.append(f"Precedence {before} -> {after} is violated.")
    requests = {(r["job"], r["resource"]): r["amount"] for r in instance["requests"]}
    for resource in instance["resources"]:
        shifts = instance["shifts"].get(resource, [])
        for job, (start, end) in normalized.items():
            amount = requests.get((job, resource), 0)
            if amount <= 0 or end <= start:
                continue
            for tick in range(start, end):
                covering = [interval for interval in shifts if interval[0] <= tick < interval[1]]
                capacity = covering[0][2] if covering else 0
                if not covering or capacity <= 0:
                    errors.append(f"Job {job} uses {resource} outside availability at {tick}.")
                    break
                usage = sum(
                    requests.get((other, resource), 0)
                    for other, (other_start, other_end) in normalized.items()
                    if other_start <= tick < other_end
                )
                if usage > capacity:
                    errors.append(f"{resource} capacity exceeded at {tick}: {usage}>{capacity}.")
                    break
    objective = 0
    if not errors:
        for order in instance["orders"]:
            end = normalized[order["sink_job"]][1]
            objective += order["weight"] * max(0, end - order["due_date"])
    return {"valid": not errors, "errors": errors, "objective": objective if not errors else None, "schedule": normalized}


def _open_client(profile: dict) -> OpenAI:
    env_name = profile.get("api_key_env")
    if env_name:
        api_key = os.getenv(env_name, "")
        if not api_key:
            raise RuntimeError(f"Environment variable {env_name} is not set")
    else:
        api_key = "lm-studio"
    return OpenAI(base_url=profile["endpoint"].rstrip("/"), api_key=api_key, timeout=profile.get("request_timeout", 60))


def _model_kwargs(profile: dict, messages: list[dict]) -> dict:
    kwargs = {"model": profile["model"], "messages": messages, "tools": llm_schema.openai_tools_schema}
    for key in ("temperature", "top_p", "max_tokens", "seed", "reasoning_effort"):
        if profile.get(key) is not None:
            kwargs[key] = profile[key]
    return kwargs


def run_turn(
    client: OpenAI,
    profile: dict,
    runtime: ToolRuntime,
    system_prompt: str,
    history: list[dict],
    prompt: str,
    *,
    max_tool_rounds: int = MAX_TOOL_ROUNDS,
    case_timeout_seconds: float | None = None,
    max_solver_time_limit: int | None = None,
    progress_callback=None,
) -> dict:
    messages = [{"role": "system", "content": system_prompt}] + _compact_history(history) + [{"role": "user", "content": prompt}]
    events = [{"type": "user", "content": prompt}]
    tool_counts: dict[str, int] = {}
    successful_mutations = 0
    invalid_retries = 0
    rounds = 0
    final_content = None
    responses = []
    finish_reasons = []
    started = time.perf_counter()
    deadline = started + case_timeout_seconds if case_timeout_seconds else None
    fatal_error = None
    while rounds < max_tool_rounds:
        rounds += 1
        if deadline is not None and time.perf_counter() >= deadline:
            fatal_error = {"type": "case_timeout", "message": "Case deadline exceeded before the next model request."}
            events.append({"type": "error", "error": fatal_error})
            break
        if progress_callback:
            progress_callback({"phase": "model_request", "round": rounds, "max_rounds": max_tool_rounds})
        try:
            response = client.chat.completions.create(**_model_kwargs(profile, messages))
        except Exception as exc:
            message_text = str(exc)
            error_type = type(exc).__name__
            if "thought_signature" in message_text.lower() or "function call is missing" in message_text.lower():
                error_type = "provider_protocol_error"
            fatal_error = {"type": error_type, "message": message_text}
            events.append({"type": "error", "error": fatal_error})
            break
        responses.append(response)
        finish_reasons.append(getattr(response.choices[0], "finish_reason", None))
        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None) or []
        content = getattr(message, "content", None) or ""
        if tool_calls:
            assistant_message = _serialize_assistant_message(message)
            messages.append(assistant_message)
            events.append({"type": "assistant", "content": content, "tool_calls": _json(assistant_message.get("tool_calls", [])), "metadata": {k: v for k, v in assistant_message.items() if k not in {"role", "content", "tool_calls"}}})
            for call in tool_calls:
                name = call.function.name
                tool_counts[name] = tool_counts.get(name, 0) + 1
                tool_elapsed = None
                args, validation_error = _validate_tool_args(name, call.function.arguments)
                if validation_error:
                    result = validation_error
                    invalid_retries += 1
                else:
                    effective_args = dict(args)
                    if name == "run_solver" and max_solver_time_limit is not None:
                        requested_limit = int(effective_args.get("time_limit", max_solver_time_limit))
                        effective_args["time_limit"] = min(requested_limit, max_solver_time_limit)
                        if requested_limit != effective_args["time_limit"]:
                            events.append({"type": "limit", "name": name, "requested_time_limit": requested_limit, "effective_time_limit": effective_args["time_limit"]})
                    tool_started = time.perf_counter()
                    if progress_callback:
                        progress_callback({"phase": "tool_started", "round": rounds, "name": name, "arguments": _json(effective_args)})
                    result = runtime.invoke(name, effective_args)
                    tool_elapsed = time.perf_counter() - tool_started
                    if name in MUTATION_TOOLS and result.get("instance_modified"):
                        successful_mutations += 1
                result = _json(result)
                events.append({"type": "tool", "name": name, "id": call.id, "arguments": _json(args if args is not None else call.function.arguments), "result": result, "revision": runtime.revision})
                if progress_callback:
                    progress_callback({"phase": "tool_finished", "round": rounds, "name": name, "elapsed_seconds": tool_elapsed})
                messages.append({"role": "tool", "tool_call_id": call.id, "name": name, "content": _compact_tool_result(name, result)})
            if invalid_retries > MAX_INVALID_TOOL_RETRIES:
                fatal_error = {"type": "invalid_tool_arguments", "message": "Model exceeded invalid tool argument retry limit."}
                events.append({"type": "error", "error": fatal_error})
                break
            continue
        final_content = content
        reasoning = getattr(message, "reasoning_content", None)
        events.append({"type": "assistant", "content": content, "reasoning": reasoning})
        history.append({"role": "user", "content": prompt})
        history.append({"role": "assistant", "content": content})
        break
    else:
        fatal_error = {"type": "tool_round_limit", "message": f"Model reached the tool-call limit ({max_tool_rounds})."}
        events.append({"type": "error", "error": fatal_error})
    usage = []
    for response in responses:
        value = getattr(response, "usage", None)
        if value is not None:
            usage.append(_json(value))
    return {
        "prompt": prompt,
        "events": events,
        "final_content": final_content,
        "fatal_error": fatal_error,
        "tool_counts": tool_counts,
        "successful_mutations": successful_mutations,
        "rounds": rounds,
        "elapsed_seconds": time.perf_counter() - started,
        "usage": usage,
        "finish_reasons": finish_reasons,
        "revision": runtime.revision,
    }


def _metric(name: str, passed: bool, details: Any = None) -> dict:
    return {"name": name, "passed": bool(passed), "details": _json(details)}


def _instance_differences(actual: dict, expected: dict) -> list[dict]:
    """Return stable JSON-path differences for human-readable diagnostics."""
    differences = []

    def walk(left: Any, right: Any, path: str = "$"):
        if isinstance(left, dict) and isinstance(right, dict):
            for key in sorted(set(left) | set(right), key=str):
                if key not in left:
                    differences.append({"path": f"{path}.{key}", "actual": None, "expected": right[key]})
                elif key not in right:
                    differences.append({"path": f"{path}.{key}", "actual": left[key], "expected": None})
                else:
                    walk(left[key], right[key], f"{path}.{key}")
            return
        if isinstance(left, list) and isinstance(right, list):
            for index in range(max(len(left), len(right))):
                child = f"{path}.{index}"
                if index >= len(left):
                    differences.append({"path": child, "actual": None, "expected": right[index]})
                elif index >= len(right):
                    differences.append({"path": child, "actual": left[index], "expected": None})
                else:
                    walk(left[index], right[index], child)
            return
        if left != right:
            differences.append({"path": path, "actual": left, "expected": right})

    walk(_canonical_instance(actual), _canonical_instance(expected))
    return differences


def evaluate_case(case: dict, runtime: ToolRuntime, reference_runtime: ToolRuntime, reference_instance: dict, turn_results: list[dict]) -> dict:
    all_events = [event for turn in turn_results for event in turn["events"]]
    tool_counts: dict[str, int] = {}
    for turn in turn_results:
        for name, count in turn["tool_counts"].items():
            tool_counts[name] = tool_counts.get(name, 0) + count
    final_text = "\n".join(turn.get("final_content") or "" for turn in turn_results)
    candidate_errors = [
        turn["fatal_error"]
        for turn in turn_results
        if turn.get("fatal_error")
    ]
    finish_reasons = [
        reason
        for turn in turn_results
        for reason in turn.get("finish_reasons", [])
        if reason
    ]
    final_result = runtime.latest_solver_result
    schedule_check = validate_schedule(runtime.instance, runtime.latest_schedule if final_result else None)
    reference_result = reference_runtime.invoke("run_solver", {"time_limit": case.get("reference_time_limit", 30)})
    reference_check = validate_schedule(reference_instance, reference_runtime.latest_schedule)
    if not reference_result.get("has_solution", False) or not reference_check["valid"]:
        return {
            "passed": False,
            "reference_error": True,
            "reference_error_details": {
                "solver": _json(reference_result),
                "schedule": reference_check,
            },
            "metrics": [],
            "diagnostics": {
                "exact_schedule_match": False,
                "reference_status": reference_result.get("status"),
                "reference_objective": None,
                "actual_objective": None,
                "returned_objective": None,
                "candidate_revision": runtime.revision,
                "solved_revision": runtime.latest_solved_revision,
                "failed_metrics": [],
                "finish_reasons": finish_reasons,
                "candidate_errors": candidate_errors,
            },
            "candidate_instance": runtime.instance,
            "reference_instance": reference_instance,
            "candidate_schedule": schedule_check.get("schedule"),
            "reference_schedule": reference_check.get("schedule"),
            "candidate_solver": _json(final_result),
            "reference_solver": _json(reference_result),
            "tool_counts": {},
            "final_response": "",
        }
    metrics = []
    metrics.append(_metric("conversation_completed", all(turn.get("fatal_error") is None and bool((turn.get("final_content") or "").strip()) for turn in turn_results)))
    metrics.append(_metric("tool_protocol_valid", not any(event.get("type") == "error" or event.get("result", {}).get("status") == "error" for event in all_events)))
    required = case.get("required_tools", {})
    if isinstance(required, list):
        required = {name: 1 for name in required}
    required_pass = all(tool_counts.get(name, 0) >= int(count) for name, count in required.items())
    metrics.append(_metric("required_tools", required_pass, {"actual": tool_counts, "required": required}))
    forbidden = case.get("forbidden_tools", [])
    forbidden_pass = all(tool_counts.get(name, 0) == 0 for name in forbidden)
    metrics.append(_metric("forbidden_tools", forbidden_pass, {"actual": tool_counts, "forbidden": forbidden}))
    instance_match = _canonical_instance(runtime.instance) == _canonical_instance(reference_instance)
    metrics.append(_metric("final_instance_match", instance_match, _instance_differences(runtime.instance, reference_instance)))
    requires_solve = case.get("requires_fresh_solve", True)
    solver_calls_this_case = tool_counts.get("run_solver", 0)
    fresh = (
        solver_calls_this_case > 0
        and final_result is not None
        and runtime.latest_solved_revision == runtime.revision
        and final_result.get("has_solution", False)
    )
    metrics.append(_metric("fresh_solve", fresh if requires_solve else True, {"revision": runtime.revision, "solved_revision": runtime.latest_solved_revision}))
    if case.get("check_schedule", True):
        metrics.append(_metric("schedule_valid", schedule_check["valid"], schedule_check["errors"]))
    else:
        metrics.append(_metric("schedule_valid", True, "disabled for this case"))
    if case.get("check_objective", True):
        actual_objective = schedule_check.get("objective")
        reference_objective = reference_check.get("objective")
        returned_objective = final_result.get("objective") if final_result else None
        objective_pass = schedule_check["valid"] and reference_check["valid"] and actual_objective == reference_objective and returned_objective == actual_objective
        metrics.append(_metric("objective_match", objective_pass, {"actual": actual_objective, "returned": returned_objective, "reference": reference_objective}))
    else:
        metrics.append(_metric("objective_match", True, "disabled for this case"))
    patterns = case.get("response_patterns", [])
    metrics.append(_metric("response_patterns", all(re.search(pattern, final_text, re.IGNORECASE | re.DOTALL) for pattern in patterns), {"patterns": patterns, "response": final_text}))
    max_mutations = case.get("max_successful_mutations")
    if max_mutations is not None:
        mutations = sum(turn.get("successful_mutations", 0) for turn in turn_results)
        metrics.append(_metric("mutation_limit", mutations <= int(max_mutations), {"actual": mutations, "maximum": max_mutations}))
    diagnostics = {
        "exact_schedule_match": bool(schedule_check.get("schedule") == reference_check.get("schedule")),
        "reference_status": reference_result.get("status"),
        "reference_objective": reference_check.get("objective"),
        "actual_objective": schedule_check.get("objective"),
        "returned_objective": final_result.get("objective") if final_result else None,
        "candidate_revision": runtime.revision,
        "solved_revision": runtime.latest_solved_revision,
        "failed_metrics": [item["name"] for item in metrics if not item["passed"]],
        "finish_reasons": finish_reasons,
        "candidate_errors": candidate_errors,
    }
    tool_policy = case.get("tool_expectations", "diagnostic")
    if tool_policy not in {"diagnostic", "hard"}:
        tool_policy = "diagnostic"
    tool_policy_pass = required_pass and forbidden_pass
    metrics.append(_metric("tool_policy", tool_policy_pass, {"mode": tool_policy, "required_tools": required, "forbidden_tools": forbidden}))
    outcome_metric_names = {"conversation_completed", "tool_protocol_valid", "final_instance_match", "fresh_solve", "schedule_valid", "objective_match", "response_patterns", "mutation_limit"}
    outcome_pass = all(item["passed"] for item in metrics if item["name"] in outcome_metric_names)
    hard_pass = outcome_pass and (tool_policy_pass if tool_policy == "hard" else True)
    diagnostics["outcome_pass"] = outcome_pass
    diagnostics["tool_policy"] = tool_policy
    diagnostics["tool_policy_pass"] = tool_policy_pass
    diagnostics["failed_metrics"] = [item["name"] for item in metrics if not item["passed"]]
    return {"passed": hard_pass, "outcome_pass": outcome_pass, "tool_policy_pass": tool_policy_pass, "metrics": metrics, "diagnostics": diagnostics, "candidate_instance": runtime.instance, "reference_instance": reference_instance, "candidate_schedule": schedule_check.get("schedule"), "reference_schedule": reference_check.get("schedule"), "candidate_solver": _json(final_result), "reference_solver": _json(reference_result), "tool_counts": tool_counts, "final_response": final_text}


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "item"


def _markdown_trace(result: dict) -> str:
    lines = [f"# {result.get('profile')} / {result.get('suite')} / {result.get('case')}", ""]
    for turn in result.get("turns", []):
        lines += ["## User", turn["prompt"], ""]
        for event in turn.get("events", []):
            if event["type"] == "assistant":
                lines += ["## Assistant", event.get("content") or "", ""]
            elif event["type"] == "tool":
                lines += [f"## Tool: `{event['name']}`", "```json", json.dumps(event, indent=2), "```", ""]
            elif event["type"] == "error":
                lines += ["## Error", "```json", json.dumps(event, indent=2), "```", ""]
    lines += ["## Evaluation", "```json", json.dumps(result.get("evaluation", {}), indent=2), "```", ""]
    return "\n".join(lines)


def run_benchmark(config: dict, config_path: Path, profile_filter: str | None = None, suite_filter: str | None = None, case_filter: str | None = None, repetitions_override: int | None = None) -> Path:
    base = Path(config["_base_dir"])
    profiles = [p for p in config["profiles"] if profile_filter is None or p["id"] == profile_filter]
    suites = [s for s in config["suites"] if suite_filter is None or s["id"] == suite_filter]
    if not profiles or not suites:
        raise ValueError("The requested profile or suite filter matched nothing")
    repetitions = repetitions_override if repetitions_override is not None else int(config["run"].get("repetitions", 1))
    max_rounds = int(config["run"].get("max_tool_rounds", 16))
    case_timeout = float(config["run"].get("case_timeout_seconds", 300))
    max_solver_time = int(config["run"].get("max_solver_time_limit", 30))
    selected_cases_by_suite = {}
    total_cases = 0
    for suite in suites:
        if case_filter is not None and suite.get("mode", "isolated") == "cumulative":
            ids = [c["id"] for c in suite["cases"]]
            if case_filter not in ids:
                selected_cases = []
            else:
                selected_cases = suite["cases"][: ids.index(case_filter) + 1]
        else:
            selected_cases = [c for c in suite["cases"] if case_filter is None or c["id"] == case_filter]
        selected_cases_by_suite[suite["id"]] = selected_cases
        total_cases += len(selected_cases) * repetitions * len(profiles)
    print(f"Benchmark: {total_cases} case(s) to run", flush=True)
    completed_cases = 0
    now = datetime.now().astimezone()
    stamp = now.strftime("%Y%m%d-%H%M%S")
    config_hash = hashlib.sha256(config_path.read_bytes()).hexdigest()[:12]
    output_root = base / config["run"].get("output_dir", "results") / f"{stamp}-{config_path.stem}"
    output_root.mkdir(parents=True, exist_ok=False)
    manifest = {"timestamp": now.isoformat(), "directory_timestamp": stamp, "config": str(config_path), "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(), "python": platform.python_version(), "platform": platform.platform(), "git_revision": None, "profiles": [{k: v for k, v in p.items() if k not in {"api_key", "api_key_value"}} for p in profiles]}
    try:
        import subprocess
        manifest["git_revision"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        pass
    (output_root / "manifest.json").write_text(json.dumps(_json(manifest), indent=2) + "\n", encoding="utf-8")
    rows = []

    def checkpoint(status: str = "running"):
        summary = {
            "status": status,
            "rows": rows,
            "total": len(rows),
            "passed": sum(bool(row["passed"]) for row in rows),
            "pass_rate": (sum(bool(row["passed"]) for row in rows) / len(rows) if rows else None),
        }
        (output_root / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        if rows:
            with (output_root / "summary.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader(); writer.writerows(rows)
    for profile in profiles:
        client = _open_client(profile)
        system_prompt = config["_resolved_profile_prompts"][profile["id"]]
        for suite in suites:
            suite_cases = selected_cases_by_suite[suite["id"]]
            if not suite_cases:
                continue
            for repetition in range(1, repetitions + 1):
                candidate_runtime = ToolRuntime(persistence_path=None)
                reference_runtime = ToolRuntime(persistence_path=None)
                base_instance = _read_json(base / suite["instance"])
                candidate_runtime.load_instance(base_instance)
                reference_runtime.load_instance(base_instance)
                history: list[dict] = []
                for case in suite_cases:
                    completed_cases += 1
                    progress_label = f"[{completed_cases}/{total_cases}] {profile['id']} / {suite['id']} / {case['id']} / attempt {repetition}"
                    print(f"{progress_label} — running", flush=True)
                    if suite.get("mode", "isolated") == "isolated":
                        candidate_runtime = ToolRuntime(persistence_path=None)
                        reference_runtime = ToolRuntime(persistence_path=None)
                        candidate_runtime.load_instance(base_instance)
                        reference_runtime.load_instance(base_instance)
                        history = []
                    reference_instance, reference_actions = _reference_for_case(case, base, reference_runtime)
                    turns = []
                    for prompt in case["prompts"]:
                        def progress(event, label=progress_label):
                            phase = event.get("phase")
                            if phase == "model_request":
                                print(f"{label} — round {event['round']}/{event['max_rounds']} requesting model", flush=True)
                            elif phase == "tool_started":
                                print(f"{label} — round {event['round']} tool {event['name']} started", flush=True)
                            elif phase == "tool_finished":
                                elapsed = event.get("elapsed_seconds")
                                suffix = f" ({elapsed:.1f}s)" if isinstance(elapsed, (int, float)) else ""
                                print(f"{label} — round {event['round']} tool {event['name']} finished{suffix}", flush=True)
                        turn = run_turn(
                            client,
                            profile,
                            candidate_runtime,
                            system_prompt,
                            history,
                            prompt,
                            max_tool_rounds=max_rounds,
                            case_timeout_seconds=case_timeout,
                            max_solver_time_limit=max_solver_time,
                            progress_callback=progress,
                        )
                        turns.append(turn)
                    evaluation = evaluate_case(case, candidate_runtime, reference_runtime, reference_instance, turns)
                    record = {"profile": profile["id"], "suite": suite["id"], "case": case["id"], "repetition": repetition, "mode": suite.get("mode", "isolated"), "reference_actions": reference_actions, "turns": turns, "evaluation": evaluation}
                    relative = Path(_slug(profile["id"])) / _slug(suite["id"]) / f"{_slug(case['id'])}-attempt-{repetition:03d}"
                    artifact_dir = output_root / relative
                    artifact_dir.mkdir(parents=True, exist_ok=True)
                    (artifact_dir / "trace.json").write_text(json.dumps(_json(record), indent=2) + "\n", encoding="utf-8")
                    (artifact_dir / "transcript.md").write_text(_markdown_trace(record), encoding="utf-8")
                    (artifact_dir / "candidate_instance.json").write_text(json.dumps(_json(evaluation["candidate_instance"]), indent=2) + "\n", encoding="utf-8")
                    (artifact_dir / "reference_instance.json").write_text(json.dumps(_json(evaluation["reference_instance"]), indent=2) + "\n", encoding="utf-8")
                    (artifact_dir / "candidate_schedule.json").write_text(json.dumps(_json(evaluation["candidate_schedule"]), indent=2) + "\n", encoding="utf-8")
                    (artifact_dir / "reference_schedule.json").write_text(json.dumps(_json(evaluation["reference_schedule"]), indent=2) + "\n", encoding="utf-8")
                    diagnostics = evaluation["diagnostics"]
                    rows.append({
                        "profile": profile["id"],
                        "suite": suite["id"],
                        "case": case["id"],
                        "repetition": repetition,
                        "passed": evaluation["passed"],
                        "outcome_pass": evaluation.get("outcome_pass", evaluation["passed"]),
                        "tool_policy_pass": evaluation.get("tool_policy_pass", True),
                        "reference_error": evaluation.get("reference_error", False),
                        "exact_schedule_match": diagnostics["exact_schedule_match"],
                        "reference_status": diagnostics.get("reference_status"),
                        "reference_objective": diagnostics["reference_objective"],
                        "actual_objective": diagnostics.get("actual_objective"),
                        "returned_objective": diagnostics.get("returned_objective"),
                        "candidate_revision": diagnostics.get("candidate_revision"),
                        "solved_revision": diagnostics.get("solved_revision"),
                        "metrics_passed": sum(m["passed"] for m in evaluation["metrics"]),
                        "metrics_total": len(evaluation["metrics"]),
                        "outcome_metrics_passed": sum(m["passed"] for m in evaluation["metrics"] if m["name"] in {"conversation_completed", "tool_protocol_valid", "final_instance_match", "fresh_solve", "schedule_valid", "objective_match", "response_patterns", "mutation_limit"}),
                        "outcome_metrics_total": sum(m["name"] in {"conversation_completed", "tool_protocol_valid", "final_instance_match", "fresh_solve", "schedule_valid", "objective_match", "response_patterns", "mutation_limit"} for m in evaluation["metrics"]),
                        "failed_metrics": ";".join(diagnostics.get("failed_metrics", [])),
                        "tool_counts": json.dumps(evaluation.get("tool_counts", {}), separators=(",", ":")),
                        "finish_reasons": ";".join(diagnostics.get("finish_reasons", [])),
                        "candidate_errors": json.dumps(diagnostics.get("candidate_errors", []), separators=(",", ":")),
                        "candidate_error_types": ";".join(
                            str(error.get("type", ""))
                            for error in diagnostics.get("candidate_errors", [])
                        ),
                        "candidate_error_messages": ";".join(
                            str(error.get("message", ""))
                            for error in diagnostics.get("candidate_errors", [])
                        ),
                    })
                    checkpoint()
                    elapsed = sum(turn.get("elapsed_seconds", 0.0) for turn in turns)
                    result_label = "PASS" if evaluation["passed"] else "FAIL"
                    print(f"{progress_label} — {result_label} ({elapsed:.1f}s)", flush=True)
                    if not evaluation["passed"] and config["run"].get("fail_fast", False):
                        raise RuntimeError(f"Benchmark failed at {profile['id']}/{suite['id']}/{case['id']}")
    with (output_root / "summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["profile", "suite", "case", "repetition", "passed"])
        writer.writeheader(); writer.writerows(rows)
    infrastructure_errors = []
    for row in rows:
        if row.get("candidate_errors"):
            errors = json.loads(row["candidate_errors"])
            for error in errors:
                if _is_infrastructure_error(error) and error not in infrastructure_errors:
                    infrastructure_errors.append(error)
    run_status = "infrastructure_error" if infrastructure_errors else "completed"
    summary = {
        "status": run_status,
        "infrastructure_errors": infrastructure_errors,
        "rows": rows,
        "total": len(rows),
        "passed": sum(bool(row["passed"]) for row in rows),
        "pass_rate": (sum(bool(row["passed"]) for row in rows) / len(rows) if rows and run_status == "completed" else None),
    }
    grouped = {}
    for row in rows:
        for dimensions in (("profile",), ("suite",), ("case",), ("profile", "suite"), ("profile", "suite", "case"), ("profile", "suite", "case", "repetition")):
            key = "/".join(str(row[name]) for name in dimensions)
            bucket = grouped.setdefault("+".join(dimensions), {}).setdefault(key, {"total": 0, "passed": 0, "outcome_passed": 0})
            bucket["total"] += 1
            bucket["passed"] += int(bool(row["passed"]))
            bucket["outcome_passed"] += int(bool(row.get("outcome_pass", row["passed"])))
    for buckets in grouped.values():
        for bucket in buckets.values():
            bucket["pass_rate"] = bucket["passed"] / bucket["total"] if bucket["total"] else None
            bucket["outcome_pass_rate"] = bucket["outcome_passed"] / bucket["total"] if bucket["total"] else None
    summary["pass_rates"] = grouped
    (output_root / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return output_root


@app.command()
def validate(config_path: str = typer.Argument(..., help="TOML benchmark configuration")):
    """Validate configuration, instances, references, and action declarations."""
    config, path = load_config(config_path)
    for suite in config["suites"]:
        instance = _read_json(Path(config["_base_dir"]) / suite["instance"])
        errors = validate_instance(instance)
        if errors:
            raise typer.BadParameter(f"Invalid instance {suite['instance']}: {errors}")
        for case in suite["cases"]:
            runtime = ToolRuntime(persistence_path=None)
            loaded = runtime.load_instance(instance)
            if loaded.get("status") != "success":
                raise typer.BadParameter(f"Could not load {suite['instance']}: {loaded}")
            try:
                reference, _ = _reference_for_case(case, Path(config["_base_dir"]), runtime)
            except ValueError as exc:
                raise typer.BadParameter(str(exc)) from exc
            reference_errors = validate_instance(reference)
            if reference_errors:
                raise typer.BadParameter(f"Invalid reference for {suite['id']}/{case['id']}: {reference_errors}")
    typer.echo(f"Valid benchmark configuration: {path}")


@app.command("run")
def run_command(config_path: str = typer.Argument(...), profile: str | None = typer.Option(None), suite: str | None = typer.Option(None), case: str | None = typer.Option(None), repetitions: int | None = typer.Option(None, min=1)):
    """Run selected model profiles and suites."""
    config, path = load_config(config_path)
    output = run_benchmark(config, path, profile, suite, case, repetitions)
    typer.echo(f"Benchmark artifacts written to {output}")


if __name__ == "__main__":
    app()
