"""Persist per-photo transform overrides (rotation per side)."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Dict

from .base_stores import BaseJSONStore


class PhotoTransformStore(BaseJSONStore):
    """JSON-backed store for per-bucket front/back rotations."""

    VERSION = 1

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        # Initialize structure if empty
        if not self._data:
            self._data = {
                "version": self.VERSION,
                "updated_at": int(time.time()),
                "transforms": {},
            }

    def _load(self) -> None:
        """Load data from JSON file with structure validation."""
        super()._load()
        # Ensure proper structure after loading
        if not isinstance(self._data.get("transforms"), dict):
            self._data.setdefault("transforms", {})
        if not isinstance(self._data.get("version"), int):
            self._data.setdefault("version", self.VERSION)
        if not isinstance(self._data.get("updated_at"), (int, float)):
            self._data.setdefault("updated_at", int(time.time()))

    def get_transform(self, bucket_prefix: str) -> Dict[str, Dict[str, int]]:
        """Get the transform for a bucket (front/back rotations)."""
        self._refresh_if_changed()
        entry = self._entry_for(bucket_prefix)
        front = entry.get("front") if isinstance(entry, dict) else None
        back = entry.get("back") if isinstance(entry, dict) else None
        return {
            "front": {"rotate": _read_rotation(front)},
            "back": {"rotate": _read_rotation(back)},
        }

    def set_rotation(self, bucket_prefix: str, side: str, rotation: int) -> int:
        """Set rotation for a bucket side (front or back)."""
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
            self._write()
        return normalized_rotation

    def _entry_for(self, bucket_prefix: str) -> Dict[str, object]:
        """Get the entry for a bucket prefix."""
        if not bucket_prefix:
            return {}
        transforms = self._data.get("transforms")
        if isinstance(transforms, dict):
            entry = transforms.get(bucket_prefix)
            if isinstance(entry, dict):
                return entry
        return {}

    def _touch_locked(self) -> None:
        """Update version and timestamp."""
        self._data["version"] = self.VERSION
        self._data["updated_at"] = int(time.time())


def _normalize_rotation(value: int) -> int:
    """Normalize rotation to 0, 90, 180, or 270 degrees."""
    try:
        rotation = int(round(float(value)))
    except (TypeError, ValueError):
        return 0
    rotation = rotation % 360
    if rotation < 0:
        rotation += 360
    return int(round(rotation / 90.0) * 90) % 360


def _read_rotation(entry) -> int:
    """Read rotation value from an entry dict."""
    if not isinstance(entry, dict):
        return 0
    value = entry.get("rotate")
    return _normalize_rotation(value)
