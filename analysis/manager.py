from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

from .sandbox import MIN_TIMEOUT_SECONDS, SandboxRunner

ROOT = Path(__file__).resolve().parents[1]
BASE_SOLVER = ROOT / "solver.py"
LIBRARY = ROOT / "analysis" / "library"
_candidate_root = Path(os.getenv("SCHEDULING_ANALYSIS_DATA", "data/analysis"))
CANDIDATES = (_candidate_root if _candidate_root.is_absolute() else ROOT / _candidate_root) / "candidates"
APPLET_LIBRARY = ROOT / "analysis" / "library" / "applets"
APPLET_CANDIDATES = (_candidate_root if _candidate_root.is_absolute() else ROOT / _candidate_root) / "applets"
MAX_APPLET_SOURCE_CHARS = 500_000
MAX_APPLET_BUNDLE_CHARS = 8_000_000
APPLET_IMPORTS = {
    "react", "react-dom", "react-dom/client", "d3", "plotly.js-dist-min",
    "cytoscape", "echarts",
}
APPLET_BLOCKED_PATTERNS = (
    r"\beval\s*\(", r"\bFunction\s*\(", r"\bfetch\s*\(",
    r"\bXMLHttpRequest\b", r"\bWebSocket\b", r"\bEventSource\b",
    r"\b(localStorage|sessionStorage)\b", r"document\s*\.\s*cookie",
    r"\b(importScripts|SharedWorker|Worker)\b", r"\bimport\s*\(",
    r"\b(innerHTML|outerHTML|insertAdjacentHTML)\b",
)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _safe_slug(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "_" for char in value).strip("_") or "candidate"


def solver_sandbox_timeout(time_limit: int, maximum: int) -> int | None:
    """Return the solver wall budget, or None when the cap is insufficient."""
    required = int(time_limit) + 30
    return required if required <= int(maximum) else None


class AnalysisManager:
    """Registry and execution boundary for scripts and solver variants."""

    def __init__(self, runtime: Any):
        self.runtime = runtime
        self.runner = SandboxRunner()
        self.active_variant: str | None = None
        CANDIDATES.mkdir(parents=True, exist_ok=True)
        APPLET_CANDIDATES.mkdir(parents=True, exist_ok=True)

    def _entries(self) -> list[dict]:
        entries = []
        for root in (LIBRARY, CANDIDATES):
            if not root.exists():
                continue
            for manifest in root.glob("*/manifest.json"):
                try:
                    item = json.loads(manifest.read_text(encoding="utf-8"))
                    item["path"] = str(manifest.parent / "script.py")
                    entries.append(item)
                except (OSError, json.JSONDecodeError):
                    continue
        return entries

    def invoke(self, name: str, arguments: dict) -> dict:
        handlers = {
            "list_analysis_scripts": self.list_scripts,
            "write_analysis_script": self.write_script,
            "run_analysis_script": self.run_script,
            "get_solver_source": self.get_solver_source,
            "write_solver_variant": self.write_solver_variant,
            "validate_solver_variant": self.validate_variant,
            "activate_solver_variant": self.activate_variant,
            "restore_base_solver": self.restore_base_solver,
            "list_visualization_applets": self.list_applets,
            "write_visualization_applet": self.write_applet,
            "run_visualization_applet": self.run_applet,
        }
        handler = handlers.get(name)
        if handler is None:
            return {"status": "error", "error_code": "unknown_tool", "message": f"Unknown analysis tool: {name}"}
        try:
            return handler(**arguments)
        except Exception as exc:
            return {"status": "error", "error_code": "analysis_manager_error", "message": str(exc), "error_type": type(exc).__name__}

    def list_scripts(self, query: str = "") -> dict:
        query = query.lower().strip()
        entries = [item for item in self._entries() if not query or query in json.dumps(item).lower()]
        return {"status": "success", "scripts": [{key: value for key, value in item.items() if key != "path"} for item in entries]}

    @staticmethod
    def _validate_analysis_source(source: str) -> list[str]:
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            return [f"Syntax error: {exc}"]
        names = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        errors = [] if "analyze" in names else ["Source must define analyze(context, parameters)."]
        blocked = {"subprocess", "socket", "ctypes", "pty"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                blocked_imports = blocked.intersection(alias.name.split(".")[0] for alias in node.names)
                errors.extend(f"Blocked import: {item}" for item in sorted(blocked_imports))
            elif isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] in blocked:
                errors.append(f"Blocked import: {node.module}")
        return sorted(set(errors))

    @staticmethod
    def _validate_visualizations(value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list) or len(value) > 20:
            return ["visualizations must be an array with at most 20 entries."]
        errors: list[str] = []
        for index, chart in enumerate(value):
            if not isinstance(chart, dict):
                errors.append(f"visualizations[{index}] must be an object.")
                continue
            kind = chart.get("kind", chart.get("type"))
            if kind == "bar":
                if not isinstance(chart.get("labels"), list) or not isinstance(chart.get("values"), list):
                    errors.append(f"visualizations[{index}] legacy bar charts require labels and values arrays.")
            elif kind == "plotly":
                if not isinstance(chart.get("spec"), dict) or not isinstance(chart["spec"].get("data"), list):
                    errors.append(f"visualizations[{index}] Plotly charts require spec.data.")
            elif kind == "echarts":
                if not isinstance(chart.get("option"), dict):
                    errors.append(f"visualizations[{index}] ECharts charts require an option object.")
            elif kind == "cytoscape":
                if not isinstance(chart.get("elements"), (list, dict)):
                    errors.append(f"visualizations[{index}] Cytoscape charts require elements.")
            else:
                errors.append(f"visualizations[{index}] uses unsupported visualization kind {kind!r}.")
            try:
                serialized = json.dumps(chart, separators=(",", ":"))
                if len(serialized) > 1_000_000:
                    errors.append(f"visualizations[{index}] exceeds the 1,000,000 character limit.")
                if any(token in serialized.lower() for token in ("<script", "javascript:", "onclick=", "onerror=")):
                    errors.append(f"visualizations[{index}] contains unsafe markup or script content.")
            except (TypeError, ValueError):
                errors.append(f"visualizations[{index}] is not JSON serializable.")
        return sorted(set(errors))

    def write_script(self, name: str, description: str, source: str) -> dict:
        errors = self._validate_analysis_source(source)
        if errors:
            return {"status": "rejected", "error_code": "invalid_analysis_source", "validation_errors": errors}
        script_id = f"candidate-{_safe_slug(name)}-{_hash(source)[:10]}"
        directory = CANDIDATES / script_id
        directory.mkdir(parents=True, exist_ok=False)
        (directory / "script.py").write_text(source, encoding="utf-8")
        (directory / "manifest.json").write_text(json.dumps({"id": script_id, "name": name, "description": description, "status": "candidate", "sha256": _hash(source), "kind": "analysis"}, indent=2) + "\n", encoding="utf-8")
        return {"status": "success", "script_id": script_id, "message": "Candidate saved; run it to sandbox-test before promotion."}

    def _find(self, script_id: str) -> tuple[dict | None, Path | None]:
        for item in self._entries():
            if item.get("id") == script_id:
                return item, Path(item["path"])
        return None, None

    def run_script(self, script_id: str, parameters: dict | None = None) -> dict:
        item, source = self._find(script_id)
        if item is None or source is None:
            return {"status": "error", "error_code": "unknown_script", "message": f"Unknown script {script_id}."}
        source_text = source.read_text(encoding="utf-8")
        if item.get("sha256") != "builtin" and _hash(source_text) != item.get("sha256"):
            return {"status": "error", "error_code": "script_hash_mismatch", "message": "The script changed after registration."}
        smoke_instance = {"instance_name": "smoke", "jobs": [1], "durations": {"1": 1}, "predecessors": {"1": []}, "resources": ["R1"], "requests": [{"job": 1, "resource": "R1", "amount": 1}], "shifts": {"R1": [[0, 2, 1]]}, "orders": [{"sink_job": 1, "due_date": 1, "weight": 1}]}
        smoke = self.runner.execute(source, {"instance": smoke_instance, "schedule": {"1": [0, 1]}, "solver_result": {"status": "optimal", "objective": 0}}, {}, kind="analysis", timeout_seconds=min(60, self.runtime.sandbox_timeout_seconds))
        if smoke.get("status") != "success":
            return {"status": "error", "error_code": "script_smoke_test_failed", "message": "The analysis script failed its known-fixture smoke test.", "smoke": smoke}
        if item.get("status") == "candidate":
            manifest_path = source.parent / "manifest.json"
            updated = {key: value for key, value in item.items() if key != "path"}
            updated["smoke_passed"] = True
            manifest_path.write_text(json.dumps(updated, indent=2) + "\n", encoding="utf-8")
        context = {"instance": self.runtime.instance, "schedule": self.runtime.latest_schedule, "solver_result": self.runtime.latest_solver_result}
        result = self.runner.execute(source, context, parameters or {}, kind="analysis", timeout_seconds=self.runtime.sandbox_timeout_seconds)
        if isinstance(result, dict) and len(json.dumps(result)) > 2_000_000:
            return {"status": "error", "error_code": "analysis_output_too_large", "message": "The analysis output exceeded the configured limit."}
        visualization_errors = self._validate_visualizations(result.get("visualizations") if isinstance(result, dict) else None)
        if visualization_errors:
            return {"status": "error", "error_code": "invalid_visualization_output", "message": "The analysis returned an unsupported or unsafe visualization payload.", "validation_errors": visualization_errors}
        if isinstance(result, dict) and any(token in json.dumps(result).lower() for token in ("<script", "javascript:", "onclick=")):
            return {"status": "error", "error_code": "unsafe_visualization", "message": "HTML and JavaScript are not allowed in analysis output."}
        return result

    @staticmethod
    def _validate_applet_source(source: str) -> list[str]:
        errors: list[str] = []
        if len(source) > MAX_APPLET_SOURCE_CHARS:
            errors.append(f"Source exceeds the {MAX_APPLET_SOURCE_CHARS} character limit.")
        if not re.search(r"export\s+(?:function\s+render|const\s+render\s*=)", source):
            errors.append("Source must export render(root, context).")
        for pattern in APPLET_BLOCKED_PATTERNS:
            if re.search(pattern, source):
                errors.append(f"Blocked browser API or construct: {pattern}")
        for module_name in re.findall(r"(?:from|import)\s*[\"']([^\"']+)[\"']", source):
            root = module_name.split("/")[0] if not module_name.startswith("@") else "/".join(module_name.split("/")[:2])
            if module_name not in APPLET_IMPORTS and root not in APPLET_IMPORTS:
                errors.append(f"Import is not allowlisted: {module_name}")
        return sorted(set(errors))

    def list_applets(self, query: str = "") -> dict:
        query = query.lower().strip()
        entries: list[dict] = []
        for root in (APPLET_LIBRARY, APPLET_CANDIDATES):
            if not root.exists():
                continue
            for manifest in root.glob("*/manifest.json"):
                try:
                    item = json.loads(manifest.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if not query or query in json.dumps(item).lower():
                    entries.append(item)
        return {"status": "success", "applets": entries}

    def write_applet(self, name: str, description: str, source: str) -> dict:
        errors = self._validate_applet_source(source)
        if errors:
            return {"status": "rejected", "error_code": "invalid_visualization_applet", "validation_errors": errors}
        applet_id = f"applet-{_safe_slug(name)}-{_hash(source)[:10]}"
        directory = APPLET_CANDIDATES / applet_id
        if directory.exists():
            return {"status": "success", "applet_id": applet_id, "source_hash": _hash(source), "message": "An immutable candidate with this source already exists."}
        directory.mkdir(parents=True, exist_ok=False)
        (directory / "source.ts").write_text(source, encoding="utf-8")
        (directory / "manifest.json").write_text(json.dumps({
            "id": applet_id, "name": name, "description": description,
            "status": "candidate", "sha256": _hash(source), "kind": "visualization_applet",
        }, indent=2) + "\n", encoding="utf-8")
        return {"status": "success", "applet_id": applet_id, "source_hash": _hash(source), "message": "Applet candidate saved; it will be compiled and smoke-tested before rendering."}

    def _find_applet(self, applet_id: str) -> tuple[dict | None, Path | None]:
        for root in (APPLET_LIBRARY, APPLET_CANDIDATES):
            manifest_path = root / applet_id / "manifest.json"
            if not manifest_path.is_file():
                continue
            try:
                item = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            source = manifest_path.parent / "source.ts"
            return item, source
        return None, None

    def run_applet(self, applet_id: str, parameters: dict | None = None, analysis_script_id: str | None = None) -> dict:
        item, source = self._find_applet(applet_id)
        if item is None or source is None or not source.is_file():
            return {"status": "error", "error_code": "unknown_visualization_applet", "message": f"Unknown visualization applet {applet_id}."}
        source_text = source.read_text(encoding="utf-8")
        source_hash = _hash(source_text)
        if item.get("sha256") != "builtin" and item.get("sha256") != source_hash:
            return {"status": "error", "error_code": "applet_hash_mismatch", "message": "The visualization applet changed after registration."}
        errors = self._validate_applet_source(source_text)
        if errors:
            return {"status": "rejected", "error_code": "invalid_visualization_applet", "validation_errors": errors}

        analysis_result = None
        if analysis_script_id:
            analysis_result = self.run_script(analysis_script_id, parameters)
            if analysis_result.get("status") not in {"success", "optimal", "feasible"}:
                return {"status": "error", "error_code": "analysis_for_applet_failed", "analysis": analysis_result}
        context = {
            "instance": self.runtime.instance,
            "schedule": self.runtime.latest_schedule,
            "solver_result": self.runtime.latest_solver_result,
            "parameters": parameters or {},
            "analysis": analysis_result,
        }
        smoke_context = {"instance": {}, "schedule": {}, "solver_result": None, "parameters": {}, "analysis": None}
        smoke = self.runner.execute(source, smoke_context, {}, kind="applet", timeout_seconds=min(60, self.runtime.sandbox_timeout_seconds))
        if smoke.get("status") != "success" or not smoke.get("bundle"):
            return {"status": "error", "error_code": "applet_smoke_test_failed", "message": "The applet failed its sandbox compilation smoke test.", "smoke": smoke}
        live = self.runner.execute(source, context, {}, kind="applet", timeout_seconds=self.runtime.sandbox_timeout_seconds)
        if live.get("status") != "success" or not live.get("bundle"):
            return {"status": "error", "error_code": "applet_compile_failed", "message": "The applet could not be compiled in the sandbox.", "result": live}
        if len(live["bundle"]) > MAX_APPLET_BUNDLE_CHARS:
            return {"status": "error", "error_code": "applet_bundle_too_large", "message": f"The compiled applet exceeds the {MAX_APPLET_BUNDLE_CHARS} character limit."}
        bundle_path = source.parent / "bundle.js"
        bundle_path.write_text(live["bundle"], encoding="utf-8")
        return {
            "status": "success",
            "visualization_type": "custom_applet",
            "applet_id": applet_id,
            "title": item.get("name", applet_id),
            "source_hash": source_hash,
            "_applet_bundle_path": str(bundle_path),
            "_applet_context": context,
        }

    def run_solver_variant(self, arguments: dict | None = None) -> dict:
        if not self.active_variant:
            return {"status": "error", "error_code": "no_active_variant", "message": "No solver variant is active."}
        item, source = self._find(self.active_variant)
        if not item:
            return {"status": "error", "error_code": "unknown_variant", "message": "The active solver variant is unavailable."}
        source = source.parent / "solver.py" if source else None
        if source is None or not source.is_file():
            return {"status": "error", "error_code": "missing_variant_source", "message": "The active solver variant source is missing."}
        solver_arguments = arguments or {}
        requested_time = int(solver_arguments.get("time_limit", 30))
        required_wall_time = solver_sandbox_timeout(requested_time, self.runtime.sandbox_timeout_seconds)
        if required_wall_time is None:
            required_wall_time = requested_time + 30
            return {
                "status": "error",
                "error_code": "sandbox_timeout_too_small",
                "message": (
                    f"This solver run requests {requested_time} seconds and needs "
                    f"{required_wall_time} seconds of sandbox wall time (including grace), "
                    f"but the conversation maximum is {self.runtime.sandbox_timeout_seconds} seconds."
                ),
                "requested_time_limit": requested_time,
                "required_wall_time": required_wall_time,
                "sandbox_timeout_seconds": self.runtime.sandbox_timeout_seconds,
            }
        context = {"instance": self.runtime.instance}
        return self.runner.execute(source, context, solver_arguments, kind="solver", timeout_seconds=required_wall_time)

    def get_solver_source(self) -> dict:
        source = BASE_SOLVER.read_text(encoding="utf-8")
        return {"status": "success", "source": source, "base_hash": _hash(source), "contract": "MRCPSP_solver(jobs,durations,predecessors,resources,requests,shifts,orders); init_model(); solve(time_limit,log_output); get_schedule()"}

    @staticmethod
    def _validate_solver_source(source: str) -> list[str]:
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            return [f"Syntax error: {exc}"]
        cls = next((node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "MRCPSP_solver"), None)
        if cls is None:
            return ["Required class MRCPSP_solver is missing."]
        methods = {node.name: node for node in cls.body if isinstance(node, ast.FunctionDef)}
        errors = [f"Missing method {name}." for name in ("__init__", "init_model", "solve", "get_schedule") if name not in methods]
        expected = {"__init__": ["self", "jobs", "durations", "predecessors", "resources", "requests", "shifts", "orders"], "init_model": ["self"], "solve": ["self", "time_limit", "log_output"], "get_schedule": ["self"]}
        for name, args in expected.items():
            node = methods.get(name)
            if node:
                actual = [arg.arg for arg in node.args.args]
                if actual[:len(args)] != args:
                    errors.append(f"{name} signature must begin with ({', '.join(args)}).")
        return errors

    def write_solver_variant(self, name: str, description: str, source: str, base_hash: str) -> dict:
        current_hash = _hash(BASE_SOLVER.read_text(encoding="utf-8"))
        if base_hash != current_hash:
            return {"status": "rejected", "error_code": "stale_solver_source", "message": "The submitted source was based on an older solver."}
        errors = self._validate_solver_source(source)
        if errors:
            return {"status": "rejected", "error_code": "invalid_solver_api", "validation_errors": errors}
        variant_id = f"variant-{_safe_slug(name)}-{_hash(source)[:10]}"
        directory = CANDIDATES / variant_id
        directory.mkdir(parents=True, exist_ok=False)
        (directory / "solver.py").write_text(source, encoding="utf-8")
        (directory / "manifest.json").write_text(json.dumps({"id": variant_id, "name": name, "description": description, "status": "candidate", "sha256": _hash(source), "kind": "solver", "base_hash": base_hash}, indent=2) + "\n", encoding="utf-8")
        return {"status": "success", "variant_id": variant_id, "message": "Variant passed static API checks; activate only after sandbox validation."}

    def activate_variant(self, variant_id: str) -> dict:
        item, source = self._find(variant_id)
        if not item or item.get("kind") != "solver":
            return {"status": "error", "error_code": "unknown_variant", "message": f"Unknown solver variant {variant_id}."}
        validation = self.validate_variant(variant_id)
        if validation.get("status") != "success":
            return validation
        self.active_variant = variant_id
        return {"status": "success", "variant_id": variant_id, "message": "Solver variant activated for this runtime."}

    def validate_variant(self, variant_id: str) -> dict:
        item, source = self._find(variant_id)
        if not item or item.get("kind") != "solver" or source is None:
            return {"status": "error", "error_code": "unknown_variant", "message": f"Unknown solver variant {variant_id}."}
        source = source.parent / "solver.py"
        errors = self._validate_solver_source(source.read_text(encoding="utf-8")) if source.is_file() else ["Variant source is missing."]
        if errors:
            return {"status": "rejected", "error_code": "invalid_solver_api", "validation_errors": errors}
        if not self.runtime.instance:
            return {"status": "success", "variant_id": variant_id, "validation": "static_api_only", "message": "Static API validation passed; load an instance for runtime validation."}
        # The validation solve itself is limited to five seconds, but the
        # sandbox API has a deliberately enforced 60-second minimum wall
        # budget.  A solver budget plus grace (5 + 30) is therefore not a
        # valid sandbox request; use the minimum accepted wall budget for this
        # quick fixture validation.  Real variant runs still use
        # ``time_limit + 30`` via ``run_solver_variant``.
        result = self.runner.execute(
            source,
            {"instance": self.runtime.instance},
            {"time_limit": 5},
            kind="solver",
            timeout_seconds=MIN_TIMEOUT_SECONDS,
        )
        if result.get("status") not in {"optimal", "feasible"} or not result.get("has_solution"):
            return {"status": "rejected", "error_code": "solver_runtime_validation_failed", "result": result}
        return {"status": "success", "variant_id": variant_id, "validation": "runtime", "result": result}

    def restore_base_solver(self) -> dict:
        self.active_variant = None
        return {"status": "success", "message": "Base solver restored."}
