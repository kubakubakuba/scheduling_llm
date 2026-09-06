"""Isolated stateful tool runtimes used by the benchmark.

The original application exposes module-level functions from ``toolcalls``.
This adapter keeps those functions backwards compatible while allowing a
benchmark attempt (and its trusted reference) to own an independent state.
"""

from __future__ import annotations

import copy
import threading
from typing import Any

from . import toolcalls


_STATE_NAMES = (
    "current_instance",
    "current_revision",
    "latest_schedule",
    "latest_obj_val",
    "latest_solver",
    "latest_solver_result",
    "latest_solved_revision",
)


class ToolRuntime:
    """Run the real scheduling tools against isolated in-memory state.

    ``persistence_path`` may be set to an artifact file, or left as ``None``
    to disable the legacy ``updated_instance.json`` write performed by
    mutation tools.
    """

    _invoke_lock = threading.RLock()

    def __init__(self, *, persistence_path: str | None = None):
        self.persistence_path = persistence_path
        self._state: dict[str, Any] = {
            "current_instance": {},
            "current_revision": 0,
            "latest_schedule": {},
            "latest_obj_val": None,
            "latest_solver": None,
            "latest_solver_result": None,
            "latest_solved_revision": None,
        }
        self.sandbox_timeout_seconds = 600
        from analysis.manager import AnalysisManager
        self.analysis = AnalysisManager(self)

    def set_sandbox_timeout(self, seconds: int) -> None:
        self.sandbox_timeout_seconds = max(60, min(3600, int(seconds)))

    def _activate(self) -> dict[str, Any]:
        previous = {name: getattr(toolcalls, name) for name in _STATE_NAMES}
        previous_path = toolcalls.persistence_path
        for name in _STATE_NAMES:
            setattr(toolcalls, name, self._state[name])
        toolcalls.persistence_path = self.persistence_path
        return {**previous, "persistence_path": previous_path}

    def _deactivate(self, previous: dict[str, Any]) -> None:
        for name in _STATE_NAMES:
            self._state[name] = getattr(toolcalls, name)
        for name in _STATE_NAMES:
            setattr(toolcalls, name, previous[name])
        toolcalls.persistence_path = previous["persistence_path"]

    def invoke(self, function_name: str, arguments: dict[str, Any] | None = None) -> dict:
        """Invoke one real tool and return its JSON-compatible result."""

        if function_name in {
            "list_analysis_scripts", "write_analysis_script", "run_analysis_script",
            "get_solver_source", "write_solver_variant", "activate_solver_variant",
            "validate_solver_variant", "restore_base_solver",
            "list_visualization_applets", "write_visualization_applet",
            "run_visualization_applet",
        }:
            with self._invoke_lock:
                return self.analysis.invoke(function_name, arguments or {})
        if function_name == "run_solver" and self.analysis.active_variant:
            result = self.analysis.run_solver_variant(arguments or {})
            if result.get("status") in {"optimal", "feasible"} and result.get("has_solution"):
                # Keep the same cache semantics as the native solver path.
                self._state["latest_solver_result"] = copy.deepcopy(result)
                self._state["latest_schedule"] = copy.deepcopy(result.get("schedule") or {})
                self._state["latest_obj_val"] = result.get("objective")
                self._state["latest_solved_revision"] = self.revision
            return result

        function = getattr(toolcalls, function_name, None)
        if function is None or function_name.startswith("_"):
            return {
                "status": "error",
                "error_code": "unknown_tool",
                "message": f"Unknown tool: {function_name}",
            }

        with self._invoke_lock:
            previous = self._activate()
            try:
                result = function(**(arguments or {}))
                return result if isinstance(result, dict) else {"result": result}
            except Exception as exc:  # tool boundary must be reportable in traces
                return {
                    "status": "error",
                    "error_code": "tool_execution_failed",
                    "message": f"{function_name} could not be completed.",
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                }
            finally:
                self._deactivate(previous)

    def load_instance(self, instance: dict) -> dict:
        return self.invoke("load_instance_data", {"candidate": copy.deepcopy(instance)})

    @property
    def instance(self) -> dict:
        return copy.deepcopy(self._state["current_instance"])

    @property
    def revision(self) -> int:
        return int(self._state["current_revision"])

    @property
    def latest_solver_result(self) -> dict | None:
        return copy.deepcopy(self._state["latest_solver_result"])

    @property
    def latest_schedule(self) -> dict:
        return copy.deepcopy(self._state["latest_schedule"])

    @property
    def latest_solved_revision(self) -> int | None:
        return self._state["latest_solved_revision"]

    def snapshot(self) -> dict[str, Any]:
        """Return JSON-safe state needed to reopen a conversation."""
        return {
            "instance": self.instance,
            "revision": self.revision,
            "latest_schedule": self.latest_schedule,
            "latest_solver_result": self.latest_solver_result,
            "latest_obj_val": self._state["latest_obj_val"],
            "latest_solved_revision": self.latest_solved_revision,
            "active_solver_variant": self.analysis.active_variant,
        }

    def restore(self, snapshot: dict[str, Any]) -> None:
        """Restore persisted state without invoking mutation tools."""
        self._state["current_instance"] = copy.deepcopy(snapshot.get("instance") or {})
        self._state["current_revision"] = int(snapshot.get("revision") or 0)
        self._state["latest_schedule"] = copy.deepcopy(snapshot.get("latest_schedule") or {})
        self._state["latest_solver_result"] = copy.deepcopy(snapshot.get("latest_solver_result"))
        self._state["latest_obj_val"] = snapshot.get("latest_obj_val")
        self._state["latest_solved_revision"] = snapshot.get("latest_solved_revision")
        self.analysis.active_variant = snapshot.get("active_solver_variant")
