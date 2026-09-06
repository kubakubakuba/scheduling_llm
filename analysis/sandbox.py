from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MIN_TIMEOUT_SECONDS = 60
MAX_TIMEOUT_SECONDS = 3600
DEFAULT_TIMEOUT_SECONDS = 600


@dataclass
class SandboxConfig:
    image: str = "diplomka-sandbox:dev"
    ibm_host_path: str = "/opt/ibm/ILOG/CPLEX_Studio222"
    ibm_container_path: str = "/opt/ibm/ILOG/CPLEX_Studio222"
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    max_timeout_seconds: int = MAX_TIMEOUT_SECONDS
    memory: str = "1g"
    cpus: str = "1"
    max_output_bytes: int = 2_000_000


class SandboxRunner:
    """Execute one fixed worker command in a disposable, offline container."""

    def __init__(self, config: SandboxConfig | None = None):
        self.config = config or SandboxConfig(
            image=os.getenv("SANDBOX_IMAGE", "diplomka-sandbox:dev"),
            ibm_host_path=os.getenv("IBM_ILOG_HOST_PATH", "/opt/ibm/ILOG/CPLEX_Studio222"),
            timeout_seconds=int(os.getenv("SANDBOX_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)),
            max_timeout_seconds=int(os.getenv("SANDBOX_ABSOLUTE_MAX_TIMEOUT_SECONDS", MAX_TIMEOUT_SECONDS)),
        )

    def execute(self, source: Path, context: dict[str, Any], parameters: dict[str, Any] | None = None, *, kind: str = "analysis", timeout_seconds: int | None = None) -> dict:
        if not source.is_file():
            return {"status": "error", "error_code": "missing_source", "message": "The requested source does not exist."}
        effective_timeout = self.config.timeout_seconds if timeout_seconds is None else int(timeout_seconds)
        operator_max = min(MAX_TIMEOUT_SECONDS, max(MIN_TIMEOUT_SECONDS, int(self.config.max_timeout_seconds)))
        if effective_timeout < MIN_TIMEOUT_SECONDS or effective_timeout > operator_max:
            return {
                "status": "error",
                "error_code": "invalid_sandbox_timeout",
                "message": f"Sandbox timeout must be between {MIN_TIMEOUT_SECONDS} and {operator_max} seconds.",
            }
        output_limit = 10_000_000 if kind == "applet" else self.config.max_output_bytes
        runner_url = os.getenv("SANDBOX_RUNNER_URL")
        if runner_url:
            payload = json.dumps({"source": source.read_text(encoding="utf-8"), "context": context, "parameters": parameters or {}, "kind": kind, "timeout_seconds": effective_timeout}).encode("utf-8")
            request = urllib.request.Request(runner_url.rstrip("/") + "/run", data=payload, headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(request, timeout=effective_timeout + 15) as response:
                    raw = response.read(output_limit + 1)
                if len(raw) > output_limit:
                    return {"status": "error", "error_code": "sandbox_output_too_large", "message": f"Sandbox output exceeded the {output_limit}-byte limit."}
                value = json.loads(raw)
                return value if isinstance(value, dict) else {"status": "error", "error_code": "invalid_runner_response"}
            except Exception as exc:
                return {"status": "error", "error_code": "sandbox_runner_unavailable", "message": str(exc)}
        payload = json.dumps({"source": source.read_text(encoding="utf-8"), "context": context, "parameters": parameters or {}, "kind": kind, "timeout_seconds": effective_timeout})
        command = [
                # `-i` keeps the container's stdin attached so the JSON payload
                # passed to subprocess.run(input=...) reaches worker_entry.py.
                "docker", "run", "--rm", "-i", "--network", "none", "--read-only",
                "--user", "65532:65532", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges", "--pids-limit", "128",
                "--memory", self.config.memory, "--cpus", self.config.cpus,
                "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
                "-e", f"CPLEX_STUDIO_DIR222={self.config.ibm_container_path}",
                "-e", f"IBM_ILOG_HOST_PATH={self.config.ibm_container_path}",
                "-v", f"{self.config.ibm_host_path}:{self.config.ibm_container_path}:ro",
                self.config.image, "python", "/opt/sandbox/worker_entry.py",
        ]
        try:
            completed = subprocess.run(command, input=payload, capture_output=True, text=True, timeout=effective_timeout + 5, check=False)
        except subprocess.TimeoutExpired:
            return {"status": "error", "error_code": "sandbox_timeout", "message": f"The sandbox exceeded its {effective_timeout}-second wall-time limit.", "timeout_seconds": effective_timeout}
        except OSError as exc:
            return {"status": "error", "error_code": "sandbox_unavailable", "message": str(exc)}
        raw_stdout = completed.stdout or ""
        raw_stderr = completed.stderr or ""
        if len(raw_stdout.encode("utf-8")) > output_limit or len(raw_stderr.encode("utf-8")) > output_limit:
            return {"status": "error", "error_code": "sandbox_output_too_large", "message": f"Sandbox output exceeded the {output_limit}-byte limit."}
        stdout = raw_stdout[: output_limit]
        stderr = raw_stderr[: output_limit]
        try:
            result = json.loads(stdout)
        except json.JSONDecodeError:
            result = None
        if completed.returncode != 0 or not isinstance(result, dict):
            return {"status": "error", "error_code": "sandbox_execution_failed", "exit_code": completed.returncode, "stdout": stdout, "stderr": stderr}
        result.setdefault("status", "success")
        result["stderr"] = stderr
        return result
