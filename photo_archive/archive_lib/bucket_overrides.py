"""Store for per-bucket configuration overrides (e.g. min_confidence)."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict

from .base_stores import BaseJSONStore


class BucketOverrideStore(BaseJSONStore):
    """JSON-backed store for bucket-level overrides."""

    VERSION = 1

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        # Wrap data in structure with overrides key
        if "overrides" not in self._data:
            self._data = {
                "version": self.VERSION,
                "updated_at": int(time.time()),
                "overrides": {},
            }

    def _load(self) -> None:
        """Load data from JSON file."""
        super()._load()
        # Extract overrides from payload structure
        if "overrides" not in self._data:
            # If _data is just the overrides dict (legacy), wrap it
            overrides = self._data if isinstance(self._data, dict) else {}
            self._data = {
                "version": self.VERSION,
                "updated_at": int(time.time()),
                "overrides": overrides,
            }

    def get(self, bucket_prefix: str) -> Dict[str, Any]:
        """Get overrides for a bucket."""
        self._refresh_if_changed()
        overrides = self._data.get("overrides", {})
        return overrides.get(bucket_prefix, {}).copy()

    def get_min_confidence(self, bucket_prefix: str, default: float) -> float:
        """Get min_confidence override for a bucket."""
        overrides = self.get(bucket_prefix)
        return float(overrides.get("min_confidence", default))

    def set_min_confidence(self, bucket_prefix: str, value: float) -> None:
        """Set min_confidence override for a bucket."""
        with self.lock:
            self._refresh_if_changed()  # Reload before mod to reduce race
            overrides = self._data.setdefault("overrides", {})
            bucket_data = overrides.setdefault(bucket_prefix, {})
            bucket_data["min_confidence"] = float(value)
            bucket_data["updated_at"] = int(time.time())
            self._data["version"] = self.VERSION
            self._data["updated_at"] = int(time.time())
            self._write()
