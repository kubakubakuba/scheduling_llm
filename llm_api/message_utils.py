"""Provider-safe chat message serialization shared by UI and benchmark loops."""

from __future__ import annotations

from typing import Any


def to_json(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): to_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json(item) for item in value]
    if hasattr(value, "model_dump"):
        return to_json(value.model_dump())
    if hasattr(value, "__dict__"):
        return to_json(vars(value))
    return str(value)


def serialize_assistant_message(message: Any) -> dict:
    """Preserve provider-specific fields on assistant tool calls.

    In particular, Gemini 3 returns a thought signature in extra content. It
    must be replayed verbatim with the following tool result request.
    """
    if hasattr(message, "model_dump"):
        result = to_json(message.model_dump(exclude_none=True))
    else:
        result = to_json(vars(message)) if hasattr(message, "__dict__") else {}
    if not isinstance(result, dict):
        result = {}
    result["role"] = "assistant"
    if not result.get("content"):
        result["content"] = getattr(message, "content", None) or ""
    calls = getattr(message, "tool_calls", None) or []
    if calls:
        serialized = []
        for call in calls:
            if hasattr(call, "model_dump"):
                item = to_json(call.model_dump(exclude_none=True))
            else:
                item = to_json(vars(call)) if hasattr(call, "__dict__") else {}
            if not isinstance(item, dict):
                item = {}
            function = getattr(call, "function", None)
            item.setdefault("id", getattr(call, "id", ""))
            item.setdefault("type", getattr(call, "type", "function"))
            item.setdefault("function", {
                "name": getattr(function, "name", ""),
                "arguments": getattr(function, "arguments", "{}"),
            })
            serialized.append(item)
        result["tool_calls"] = serialized
    return result
