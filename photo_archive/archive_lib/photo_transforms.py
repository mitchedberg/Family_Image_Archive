"""Persist per-photo transform overrides (rotation per side)."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Dict


class PhotoTransformStore:
    """JSON-backed store for per-bucket front/back rotations."""

    VERSION = 1

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()
        self._data: Dict[str, object] = {
            "version": self.VERSION,
            "updated_at": int(time.time()),
            "transforms": {},
        }
        self._mtime = 0
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._mtime = 0
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        transforms = payload.get("transforms")
        if isinstance(transforms, dict):
            self._data["transforms"] = transforms
        version = payload.get("version")
        if isinstance(version, int) and version > 0:
            self._data["version"] = version
        updated = payload.get("updated_at")
        if isinstance(updated, (int, float)):
            self._data["updated_at"] = int(updated)
        self._mtime = self._stat_mtime()

    def get_transform(self, bucket_prefix: str) -> Dict[str, Dict[str, int]]:
        self._refresh_if_changed()
        entry = self._entry_for(bucket_prefix)
        front = entry.get("front") if isinstance(entry, dict) else None
        back = entry.get("back") if isinstance(entry, dict) else None
        return {
            "front": {"rotate": _read_rotation(front)},
            "back": {"rotate": _read_rotation(back)},
        }

    def set_rotation(self, bucket_prefix: str, side: str, rotation: int) -> int:
        self._refresh_if_changed()
        clean_bucket = (bucket_prefix or "").strip()
        if not clean_bucket:
            raise ValueError("bucket_prefix is required")
        normalized_side = (side or "").strip().lower()
        if normalized_side not in {"front", "back"}:
            raise ValueError("side must be 'front' or 'back'")
        normalized_rotation = _normalize_rotation(rotation)
        with self.lock:
            transforms = self._data.setdefault("transforms", {})
            entry = transforms.get(clean_bucket)
            if not isinstance(entry, dict):
                entry = {}
                transforms[clean_bucket] = entry
            if normalized_rotation == 0:
                entry.pop(normalized_side, None)
            else:
                entry[normalized_side] = {"rotate": normalized_rotation}
            if not entry:
                transforms.pop(clean_bucket, None)
            self._touch_locked()
            self._write_locked()
        return normalized_rotation

    def _entry_for(self, bucket_prefix: str) -> Dict[str, object]:
        if not bucket_prefix:
            return {}
        transforms = self._data.get("transforms")
        if isinstance(transforms, dict):
            entry = transforms.get(bucket_prefix)
            if isinstance(entry, dict):
                return entry
        return {}

    def _touch_locked(self) -> None:
        self._data["version"] = self.VERSION
        self._data["updated_at"] = int(time.time())

    def _write_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(self.path)
        self._mtime = self._stat_mtime()

    def _refresh_if_changed(self) -> None:
        current = self._stat_mtime()
        if current == self._mtime:
            return
        self._load()

    def _stat_mtime(self) -> int:
        try:
            return int(self.path.stat().st_mtime_ns)
        except FileNotFoundError:
            return 0


def _normalize_rotation(value: int) -> int:
    try:
        rotation = int(round(float(value)))
    except (TypeError, ValueError):
        return 0
    rotation = rotation % 360
    if rotation < 0:
        rotation += 360
    return int(round(rotation / 90.0) * 90) % 360


def _read_rotation(entry) -> int:
    if not isinstance(entry, dict):
        return 0
    value = entry.get("rotate")
    return _normalize_rotation(value)
