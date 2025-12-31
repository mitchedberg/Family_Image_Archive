"""CSV-backed store for bucket-level rejects per person label."""
from __future__ import annotations

import csv
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Set, Tuple

from .label_utils import normalize_label


class LabelBucketRejectStore:
    """Persist (label, bucket_prefix) rejects so queues can skip them."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._entries: Dict[Tuple[str, str], Dict[str, str]] = {}
        self._mtime = 0
        self._load()

    def _load(self) -> None:
        entries: Dict[Tuple[str, str], Dict[str, str]] = {}
        if self.path.exists():
            try:
                with self.path.open("r", newline="", encoding="utf-8") as handle:
                    reader = csv.DictReader(handle)
                    for row in reader:
                        label = (row.get("label") or "").strip()
                        normalized = normalize_label(label)
                        bucket_prefix = (row.get("bucket_prefix") or "").strip()
                        ts = (row.get("updated_at_utc") or "").strip()
                        if not normalized or not bucket_prefix:
                            continue
                        key = (normalized, bucket_prefix)
                        entries[key] = {
                            "label": label,
                            "bucket_prefix": bucket_prefix,
                            "updated_at_utc": ts,
                        }
            except Exception:
                entries = {}
        with self.lock:
            self._entries = entries
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

    def rejected_buckets_for(self, label: str) -> Set[str]:
        normalized = normalize_label(label)
        if not normalized:
            return set()
        self._refresh_if_changed()
        return {bucket for (lbl, bucket) in self._entries if lbl == normalized}

    def add(self, label: str, bucket_prefix: str) -> Dict[str, str]:
        clean_bucket = (bucket_prefix or "").strip()
        clean_label = (label or "").strip()
        normalized = normalize_label(clean_label)
        if not clean_bucket or not normalized:
            raise ValueError("label and bucket_prefix are required")
        record = {
            "label": clean_label,
            "bucket_prefix": clean_bucket,
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        key = (normalized, clean_bucket)
        self._refresh_if_changed()
        with self.lock:
            self._entries[key] = record
            self._write_locked()
        return dict(record)

    def remove(self, label: str, bucket_prefix: str) -> bool:
        normalized = normalize_label(label)
        clean_bucket = (bucket_prefix or "").strip()
        if not normalized or not clean_bucket:
            return False
        key = (normalized, clean_bucket)
        self._refresh_if_changed()
        with self.lock:
            if key not in self._entries:
                return False
            del self._entries[key]
            self._write_locked()
            return True

    def list_for(self, label: str) -> List[Dict[str, str]]:
        normalized = normalize_label(label)
        if not normalized:
            return []
        self._refresh_if_changed()
        return [
            dict(record)
            for (lbl, _), record in self._entries.items()
            if lbl == normalized
        ]

    def all(self) -> List[Dict[str, str]]:
        self._refresh_if_changed()
        return [dict(record) for record in self._entries.values()]

    def _write_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", newline="", encoding="utf-8") as handle:
            fieldnames = ["label", "bucket_prefix", "updated_at_utc"]
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for (_, _), record in sorted(
                self._entries.items(), key=lambda item: (item[0][0], item[0][1])
            ):
                writer.writerow(
                    {
                        "label": record.get("label", ""),
                        "bucket_prefix": record.get("bucket_prefix", ""),
                        "updated_at_utc": record.get("updated_at_utc", ""),
                    }
                )
        self._mtime = self._stat_mtime()
