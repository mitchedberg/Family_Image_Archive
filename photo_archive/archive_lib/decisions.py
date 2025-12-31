"""Helpers for loading and persisting AI review decisions."""
from __future__ import annotations

import csv
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from datetime import datetime, timezone

CHOICES = {"prefer_ai", "prefer_original", "flag_creepy"}


@dataclass
class Decision:
    bucket_prefix: str
    choice: str
    note: str = ""
    updated_at_utc: str = ""


class DecisionStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: Dict[str, Decision] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        with self.path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                bucket = row.get("bucket_prefix") or ""
                choice = row.get("choice") or ""
                if not bucket or choice not in CHOICES:
                    continue
                self._data[bucket] = Decision(
                    bucket_prefix=bucket,
                    choice=choice,
                    note=row.get("note", ""),
                    updated_at_utc=row.get("updated_at_utc", ""),
                )

    def all(self) -> Dict[str, Decision]:
        return dict(self._data)

    def update(self, bucket_prefix: str, choice: str, note: str = "") -> Decision:
        if choice not in CHOICES:
            raise ValueError(f"Unsupported choice: {choice}")
        ts = datetime.now(timezone.utc).isoformat()
        decision = Decision(bucket_prefix=bucket_prefix, choice=choice, note=note, updated_at_utc=ts)
        with self.lock:
            self._data[bucket_prefix] = decision
            self._write()
        return decision

    def clear(self, bucket_prefix: str) -> None:
        with self.lock:
            if bucket_prefix in self._data:
                del self._data[bucket_prefix]
                self._write()

    def _write(self) -> None:
        with self.path.open("w", newline="", encoding="utf-8") as handle:
            fieldnames = ["bucket_prefix", "choice", "note", "updated_at_utc"]
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for decision in self._data.values():
                writer.writerow(
                    {
                        "bucket_prefix": decision.bucket_prefix,
                        "choice": decision.choice,
                        "note": decision.note,
                        "updated_at_utc": decision.updated_at_utc,
                    }
                )
