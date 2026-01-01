"""Store for tracking per-photo (bucket) priority for photo tagging."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Dict

from .json_store import BaseJSONStore


class PhotoPriorityStore(BaseJSONStore):
    """Track per-photo (bucket) priority for photo tagging.

    Manages priority levels (low, normal, high) for photo buckets to help
    users organize their tagging workflow. Only non-default priorities are
    stored to keep the file small.

    Thread-safe with atomic file writes.
    """

    VERSION = 1
    DEFAULT_PRIORITY = "normal"
    VALID_PRIORITIES = {"low", "normal", "high"}

    def _init_data(self) -> Dict[str, object]:
        """Initialize data structure with priorities dict."""
        return {
            "version": self.VERSION,
            "updated_at": int(time.time()),
            "priorities": {},
        }

    def _load(self) -> None:
        """Load and validate priorities from JSON file."""
        if not self.path.exists():
            return
        try:
            import json
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}

        # Validate and clean priorities
        priorities = payload.get("priorities")
        if isinstance(priorities, dict):
            cleaned = {}
            for bucket, value in priorities.items():
                if not isinstance(bucket, str):
                    continue
                if isinstance(value, str) and value.lower() in self.VALID_PRIORITIES and bucket.strip():
                    cleaned[bucket.strip()] = value.lower()
            self._data["priorities"] = cleaned

        # Update version if valid
        version = payload.get("version")
        if isinstance(version, int) and version > 0:
            self._data["version"] = version

        # Update timestamp if valid
        updated = payload.get("updated_at")
        if isinstance(updated, (int, float)):
            self._data["updated_at"] = int(updated)

    def get_priority(self, bucket_prefix: str) -> str:
        """Get priority for a bucket.

        Args:
            bucket_prefix: Bucket identifier

        Returns:
            Priority level: "low", "normal", or "high"
        """
        if not bucket_prefix:
            return self.DEFAULT_PRIORITY
        entry = self._data.get("priorities") or {}
        value = entry.get(bucket_prefix)
        if isinstance(value, str) and value in self.VALID_PRIORITIES:
            return value
        return self.DEFAULT_PRIORITY

    def set_priority(self, bucket_prefix: str, priority: str) -> str:
        """Set priority for a bucket.

        Args:
            bucket_prefix: Bucket identifier
            priority: Priority level ("low", "normal", or "high")

        Returns:
            The normalized priority value

        Raises:
            ValueError: If bucket_prefix is empty or priority is invalid
        """
        clean_bucket = (bucket_prefix or "").strip()
        if not clean_bucket:
            raise ValueError("bucket_prefix is required")
        normalized = (priority or "").strip().lower()
        if normalized not in self.VALID_PRIORITIES:
            raise ValueError("priority must be one of: low, normal, high")

        with self.lock:
            priorities = self._data.setdefault("priorities", {})
            # Only store non-default priorities to keep file small
            if normalized == self.DEFAULT_PRIORITY:
                priorities.pop(clean_bucket, None)
            else:
                priorities[clean_bucket] = normalized
            self._touch_locked()
            self._write_locked()
        return normalized
