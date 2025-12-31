"""Store for per-bucket configuration overrides (e.g. min_confidence)."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Dict, Optional, Any


class BucketOverrideStore:
    """JSON-backed store for bucket-level overrides."""

    VERSION = 1

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()
        self._data: Dict[str, Dict[str, Any]] = {}
        self._mtime = 0
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._data = {}
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            self._data = payload.get("overrides", {})
        except Exception:
            self._data = {}
        self._mtime = self._stat_mtime()

    def _stat_mtime(self) -> int:
        try:
            return int(self.path.stat().st_mtime_ns)
        except FileNotFoundError:
            return 0

    def _refresh_if_changed(self) -> None:
        current = self._stat_mtime()
        if current == self._mtime:
            return
        self._load()

    def get(self, bucket_prefix: str) -> Dict[str, Any]:
        self._refresh_if_changed()
        return self._data.get(bucket_prefix, {}).copy()

    def get_min_confidence(self, bucket_prefix: str, default: float) -> float:
        overrides = self.get(bucket_prefix)
        return float(overrides.get("min_confidence", default))

    def set_min_confidence(self, bucket_prefix: str, value: float) -> None:
        with self.lock:
            self._refresh_if_changed() # Reload before mod to reduce race
            bucket_data = self._data.setdefault(bucket_prefix, {})
            bucket_data["min_confidence"] = float(value)
            bucket_data["updated_at"] = int(time.time())
            self._write_locked()

    def _write_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": self.VERSION,
            "updated_at": int(time.time()),
            "overrides": self._data,
        }
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(self.path)
        self._mtime = self._stat_mtime()
