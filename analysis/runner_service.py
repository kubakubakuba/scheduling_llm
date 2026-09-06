from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .sandbox import SandboxRunner

app = FastAPI(title="Scheduling sandbox runner")


class RunRequest(BaseModel):
    source: str
    context: dict
    parameters: dict = Field(default_factory=dict)
    kind: Literal["analysis", "solver", "applet"] = "analysis"
    timeout_seconds: int = Field(default=600, ge=60, le=3600)


@app.get("/health")
def health():
    """Report runner readiness, including the Docker socket used for workers.

    A listening HTTP process alone is not sufficient: the runner must be able
    to launch disposable containers.  Exposing these checks makes a
    backend/runner connectivity problem distinguishable from a runner/Docker
    problem.
    """
    docker_path = shutil.which("docker")
    docker_version = None
    docker_error = None
    if docker_path:
        try:
            check = subprocess.run(
                [docker_path, "version", "--format", "{{.Server.Version}}"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            if check.returncode == 0:
                docker_version = check.stdout.strip() or "unknown"
            else:
                docker_error = (check.stderr or check.stdout).strip() or "docker version failed"
        except (OSError, subprocess.TimeoutExpired) as exc:
            docker_error = str(exc)
    else:
        docker_error = "docker executable is not installed in the runner image"

    ibm_path = os.getenv("IBM_ILOG_HOST_PATH", "/opt/ibm/ILOG/CPLEX_Studio222")
    ibm_available = Path(ibm_path).is_dir()
    ready = docker_version is not None
    return {
        "status": "ok" if ready else "error",
        "docker": {"available": ready, "version": docker_version, "error": docker_error},
        "ibm_installation": {"path": ibm_path, "available": ibm_available},
    }


@app.post("/run")
def run(request: RunRequest):
    with tempfile.TemporaryDirectory(prefix="runner-source-") as directory:
        source = Path(directory) / "source.py"
        source.write_text(request.source, encoding="utf-8")
        # Let SandboxRunner read the configured worker image and host IBM path
        # from this service's environment.
        runner = SandboxRunner()
        return runner.execute(source, request.context, request.parameters, kind=request.kind, timeout_seconds=request.timeout_seconds)
