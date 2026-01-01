"""Helpers for loading and persisting AI review decisions."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from datetime import datetime, timezone

from .base_stores import BaseCSVStore

CHOICES = {"prefer_ai", "prefer_original", "flag_creepy"}


@dataclass
class Decision:
    bucket_prefix: str
    choice: str
    note: str = ""
    updated_at_utc: str = ""


class DecisionStore(BaseCSVStore[Decision]):
    """Store for AI review decisions, persisted to CSV."""

    @property
    def fieldnames(self) -> List[str]:
        """Return CSV column names."""
        return ["bucket_prefix", "choice", "note", "updated_at_utc"]

    def _parse_row(self, row: Dict[str, str]) -> Decision | None:
        """Parse a CSV row into a Decision object."""
        bucket = row.get("bucket_prefix") or ""
        choice = row.get("choice") or ""
        if not bucket or choice not in CHOICES:
            return None
        return Decision(
            bucket_prefix=bucket,
            choice=choice,
            note=row.get("note", ""),
            updated_at_utc=row.get("updated_at_utc", ""),
        )

    def _row_dict(self, item: Decision) -> Dict[str, Any]:
        """Convert a Decision object to a CSV row dict."""
        return {
            "bucket_prefix": item.bucket_prefix,
            "choice": item.choice,
            "note": item.note,
            "updated_at_utc": item.updated_at_utc,
        }

    def _get_key(self, item: Decision) -> str:
        """Return the key for storing the decision (bucket_prefix)."""
        return item.bucket_prefix

    def update(self, bucket_prefix: str, choice: str, note: str = "") -> Decision:
        """Update or create a decision for a bucket."""
        if choice not in CHOICES:
            raise ValueError(f"Unsupported choice: {choice}")
        ts = datetime.now(timezone.utc).isoformat()
        decision = Decision(bucket_prefix=bucket_prefix, choice=choice, note=note, updated_at_utc=ts)
        with self.lock:
            self._data[bucket_prefix] = decision
            self._write()
        return decision

    def clear(self, bucket_prefix: str) -> None:
        """Remove a decision for a bucket."""
        with self.lock:
            if bucket_prefix in self._data:
                del self._data[bucket_prefix]
                self._write()
