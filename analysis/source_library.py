"""Persistent, immutable source library shared by the UI and agent tools."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal


ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "analysis" / "library"
_candidate_root = Path(os.getenv("SCHEDULING_ANALYSIS_DATA", "data/analysis"))
DATA_ROOT = _candidate_root if _candidate_root.is_absolute() else ROOT / _candidate_root
CANDIDATES = DATA_ROOT / "candidates"
APPLET_LIBRARY = LIBRARY / "applets"
APPLET_CANDIDATES = DATA_ROOT / "applets"

LibraryKind = Literal["analysis", "visualization"]


def source_hash(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def safe_slug(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "_" for char in value).strip("_") or "candidate"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SourceLibrary:
    """Read and mutate source entries without exposing arbitrary filesystem paths."""

    _lock = threading.RLock()

    def __init__(
        self,
        *,
        library_root: Path = LIBRARY,
        candidate_root: Path = CANDIDATES,
        applet_library_root: Path = APPLET_LIBRARY,
        applet_candidate_root: Path = APPLET_CANDIDATES,
    ):
        self.library_root = Path(library_root)
        self.candidate_root = Path(candidate_root)
        self.applet_library_root = Path(applet_library_root)
        self.applet_candidate_root = Path(applet_candidate_root)
        self.candidate_root.mkdir(parents=True, exist_ok=True)
        self.applet_candidate_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def normalize_kind(kind: str) -> LibraryKind:
        if kind == "analysis":
            return "analysis"
        if kind in {"visualization", "visualization_applet"}:
            return "visualization"
        raise ValueError(f"Unsupported library kind: {kind}")

    def _locations(self, kind: LibraryKind) -> tuple[tuple[Path, str], ...]:
        if kind == "analysis":
            return ((self.library_root, "bundled"), (self.candidate_root, "generated"))
        return ((self.applet_library_root, "bundled"), (self.applet_candidate_root, "generated"))

    @staticmethod
    def _source_name(kind: LibraryKind) -> str:
        return "script.py" if kind == "analysis" else "source.ts"

    def _read_at(self, kind: LibraryKind, directory: Path, origin: str, include_source: bool) -> dict | None:
        manifest_path = directory / "manifest.json"
        source_path = directory / self._source_name(kind)
        if not manifest_path.is_file() or not source_path.is_file():
            return None
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            source = source_path.read_text(encoding="utf-8")
        except (OSError, json.JSONDecodeError):
            return None
        expected_kind = "analysis" if kind == "analysis" else "visualization_applet"
        if manifest.get("kind", expected_kind) != expected_kind:
            return None
        entry = {
            "id": str(manifest.get("id") or directory.name),
            "kind": kind,
            "name": str(manifest.get("name") or directory.name),
            "description": str(manifest.get("description") or ""),
            "origin": origin,
            "status": str(manifest.get("status") or ("verified" if origin == "bundled" else "candidate")),
            "smoke_passed": bool(manifest.get("smoke_passed") or origin == "bundled"),
            "source_hash": source_hash(source),
            "parent_id": manifest.get("parent_id"),
            "created_at": manifest.get("created_at"),
            "editable": True,
            "deletable": origin == "generated",
        }
        if include_source:
            entry["source"] = source
        return entry

    def list_items(self, *, kind: str | None = None, status: str = "", query: str = "") -> list[dict]:
        kinds = (self.normalize_kind(kind),) if kind else ("analysis", "visualization")
        query_value = query.strip().lower()
        status_value = status.strip().lower()
        entries: dict[tuple[str, str], dict] = {}
        for item_kind in kinds:
            for root, origin in self._locations(item_kind):
                if not root.exists():
                    continue
                for manifest_path in root.glob("*/manifest.json"):
                    item = self._read_at(item_kind, manifest_path.parent, origin, False)
                    if item is None:
                        continue
                    if status_value and item["status"].lower() != status_value:
                        continue
                    searchable = " ".join(str(item.get(key, "")) for key in ("id", "name", "description", "kind", "origin", "status")).lower()
                    if query_value and query_value not in searchable:
                        continue
                    key = (item["kind"], item["id"])
                    if key not in entries or item["origin"] == "bundled":
                        entries[key] = item
        return sorted(entries.values(), key=lambda item: (item["kind"], item["name"].lower(), item["id"]))

    def get_item(self, kind: str, item_id: str, *, include_source: bool = True) -> dict | None:
        normalized_kind = self.normalize_kind(kind)
        if not item_id or item_id in {".", ".."} or "/" in item_id or "\\" in item_id:
            return None
        for root, origin in self._locations(normalized_kind):
            root_resolved = root.resolve()
            candidates = [(root / item_id).resolve()]
            candidates.extend(path.parent.resolve() for path in root.glob("*/manifest.json"))
            seen: set[Path] = set()
            for directory in candidates:
                if directory in seen or directory.parent != root_resolved:
                    continue
                seen.add(directory)
                item = self._read_at(normalized_kind, directory, origin, include_source)
                if item is not None and item["id"] == item_id:
                    return item
        return None

    def source_path(self, kind: str, item_id: str) -> Path | None:
        normalized_kind = self.normalize_kind(kind)
        if not item_id or item_id in {".", ".."} or "/" in item_id or "\\" in item_id:
            return None
        for root, origin in self._locations(normalized_kind):
            root_resolved = root.resolve()
            for manifest_path in root.glob("*/manifest.json"):
                directory = manifest_path.parent.resolve()
                if directory.parent != root_resolved:
                    continue
                item = self._read_at(normalized_kind, directory, origin, False)
                if item is not None and item["id"] == item_id:
                    return directory / self._source_name(normalized_kind)
        return None

    def create_candidate(
        self,
        kind: str,
        *,
        name: str,
        description: str,
        source: str,
        smoke_passed: bool = False,
        parent_id: str | None = None,
    ) -> dict:
        normalized_kind = self.normalize_kind(kind)
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("A library item name is required.")
        digest = source_hash(source)
        prefix = "candidate" if normalized_kind == "analysis" else "applet"
        item_id = f"{prefix}-{safe_slug(clean_name)}-{digest[:10]}"
        root = self.candidate_root if normalized_kind == "analysis" else self.applet_candidate_root
        destination = root / item_id
        with self._lock:
            existing = self.get_item(normalized_kind, item_id)
            if existing is not None:
                return existing
            temporary = root / f".{item_id}-{uuid.uuid4().hex}.tmp"
            temporary.mkdir(parents=False, exist_ok=False)
            try:
                manifest = {
                    "id": item_id,
                    "name": clean_name,
                    "description": description.strip(),
                    "status": "candidate",
                    "sha256": digest,
                    "kind": "analysis" if normalized_kind == "analysis" else "visualization_applet",
                    "smoke_passed": bool(smoke_passed),
                    "created_at": _now(),
                }
                if parent_id:
                    manifest["parent_id"] = parent_id
                (temporary / self._source_name(normalized_kind)).write_text(source, encoding="utf-8")
                (temporary / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
                temporary.replace(destination)
            except Exception:
                shutil.rmtree(temporary, ignore_errors=True)
                raise
        created = self.get_item(normalized_kind, item_id)
        if created is None:
            raise OSError("The library candidate could not be read after creation.")
        return created

    def mark_smoke_passed(self, kind: str, item_id: str) -> None:
        normalized_kind = self.normalize_kind(kind)
        item = self.get_item(normalized_kind, item_id, include_source=False)
        if item is None or item["origin"] != "generated" or item["smoke_passed"]:
            return
        root = self.candidate_root if normalized_kind == "analysis" else self.applet_candidate_root
        manifest_path = root / item_id / "manifest.json"
        with self._lock:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["smoke_passed"] = True
            manifest["validated_at"] = _now()
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    def delete_item(self, kind: str, item_id: str) -> dict:
        normalized_kind = self.normalize_kind(kind)
        item = self.get_item(normalized_kind, item_id, include_source=False)
        if item is None:
            raise KeyError(item_id)
        if item["origin"] != "generated":
            raise PermissionError("Bundled library entries cannot be deleted.")
        root = (self.candidate_root if normalized_kind == "analysis" else self.applet_candidate_root).resolve()
        directory = (root / item_id).resolve()
        if directory.parent != root or not directory.is_dir():
            raise KeyError(item_id)
        with self._lock:
            shutil.rmtree(directory)
        return item
