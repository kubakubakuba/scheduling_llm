"""Entrypoint copied into the sandbox image, not executed by the backend."""

from __future__ import annotations

import importlib.util
import json
import sys
import os
import subprocess
from docplex.cp.config import context as cp_context
from pathlib import Path


def main():
    root = os.getenv("CPLEX_STUDIO_DIR222") or os.getenv("IBM_ILOG_HOST_PATH")
    if root:
        candidate = Path(root) / "cpoptimizer" / "bin" / "x86-64_linux" / "cpoptimizer"
        if candidate.is_file():
            cp_context.solver.local.execfile = str(candidate)
    payload = json.loads(sys.stdin.read())
    if payload.get("kind") == "applet":
        try:
            compiled = subprocess.run(
                ["node", "/opt/sandbox/applet_worker.mjs"],
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                timeout=int(payload.get("timeout_seconds", 600)),
                check=False,
            )
        except subprocess.TimeoutExpired:
            print(json.dumps({"status": "error", "error_code": "applet_compile_timeout", "message": "The applet compiler exceeded its sandbox deadline."}), flush=True)
            return
        if compiled.returncode != 0:
            print(json.dumps({"status": "error", "error_code": "applet_compile_failed", "message": (compiled.stderr or compiled.stdout or "TypeScript applet compilation failed.").strip()}), flush=True)
            return
        try:
            result = json.loads(compiled.stdout)
        except json.JSONDecodeError:
            print(json.dumps({"status": "error", "error_code": "applet_compile_failed", "message": "Applet compiler returned invalid JSON."}), flush=True)
            return
        if not isinstance(result, dict):
            raise TypeError("Applet compiler returned a non-object result")
        print(json.dumps(result), flush=True)
        return
    source = Path("/tmp/candidate.py")
    source.write_text(payload["source"], encoding="utf-8")
    spec = importlib.util.spec_from_file_location("candidate", source)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    if payload["kind"] == "analysis":
        result = module.analyze(payload["context"], payload["parameters"])
    else:
        instance = payload["context"]["instance"]
        solver = module.MRCPSP_solver(
            jobs=instance["jobs"],
            durations={int(key): value for key, value in instance["durations"].items()},
            predecessors={int(key): [int(item) for item in value] for key, value in instance["predecessors"].items()},
            resources=instance["resources"],
            requests={(item["job"], item["resource"]): item["amount"] for item in instance["requests"]},
            shifts=instance["shifts"],
            orders=instance["orders"],
        )
        solver.init_model()
        result = solver.solve(time_limit=payload["parameters"].get("time_limit", 30), log_output=False)
        if result.get("has_solution"):
            result["schedule"] = {str(key): list(value) for key, value in (solver.get_schedule() or {}).items()}
    if not isinstance(result, dict):
        raise TypeError("Worker entrypoint must return a JSON object")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
