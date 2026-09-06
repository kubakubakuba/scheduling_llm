"""Promotion utilities for the immutable analysis-script library."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from .manager import CANDIDATES, LIBRARY, _safe_slug


def promote_candidate(candidate_id: str, *, library_root: Path = LIBRARY) -> Path:
    source_dir = CANDIDATES / candidate_id
    manifest_path = source_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(candidate_id)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("kind") != "analysis":
        raise ValueError("Only analysis scripts can be promoted with this function")
    if not manifest.get("smoke_passed"):
        raise ValueError("Candidate must pass its sandbox smoke test before promotion")
    destination = library_root / _safe_slug(manifest.get("name", candidate_id))
    if destination.exists():
        raise FileExistsError(destination)
    destination.mkdir(parents=True)
    shutil.copy2(source_dir / "script.py", destination / "script.py")
    manifest["status"] = "verified"
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return destination
