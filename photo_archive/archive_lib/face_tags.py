"""Utility helpers for storing per-face labels."""
from __future__ import annotations

import csv
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict


@dataclass
class FaceTag:
    face_id: str
    bucket_prefix: str
    face_index: int
    label: str
    note: str = ""
    updated_at_utc: str = ""


class FaceTagStore:
    """Simple CSV-backed store for labeling detected faces."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: Dict[str, FaceTag] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        with self.path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                face_id = (row.get("face_id") or "").strip()
                label = (row.get("label") or "").strip()
                if not face_id:
                    continue
                try:
                    face_index = int(row.get("face_index") or "0")
                except ValueError:
                    face_index = 0
                self._data[face_id] = FaceTag(
                    face_id=face_id,
                    bucket_prefix=(row.get("bucket_prefix") or "").strip(),
                    face_index=face_index,
                    label=label,
                    note=row.get("note", "").strip(),
                    updated_at_utc=row.get("updated_at_utc", ""),
                )

    def all(self) -> Dict[str, FaceTag]:
        return dict(self._data)

    def update(self, face_id: str, bucket_prefix: str, face_index: int, label: str, note: str = "") -> FaceTag:
        label = label.strip()
        if not face_id or not label:
            raise ValueError("face_id and label are required")
        timestamp = datetime.now(timezone.utc).isoformat()
        tag = FaceTag(
            face_id=face_id,
            bucket_prefix=bucket_prefix,
            face_index=face_index,
            label=label,
            note=note.strip(),
            updated_at_utc=timestamp,
        )
        with self.lock:
            self._data[face_id] = tag
            self._write()
        return tag

    def clear(self, face_id: str) -> None:
        if not face_id:
            return
        with self.lock:
            if face_id in self._data:
                del self._data[face_id]
                self._write()

    def merge_labels(self, source_label: str, target_label: str) -> int:
        """Reassign every face tagged with source_label to target_label."""
        source_label = source_label.strip()
        target_label = target_label.strip()
        if not source_label or not target_label or source_label == target_label:
            return 0
        updated = 0
        timestamp = datetime.now(timezone.utc).isoformat()
        with self.lock:
            for tag in self._data.values():
                if tag.label != source_label:
                    continue
                tag.label = target_label
                tag.updated_at_utc = timestamp
                updated += 1
            if updated:
                self._write()
        return updated

    def _write(self) -> None:
        with self.path.open("w", newline="", encoding="utf-8") as handle:
            fieldnames = ["face_id", "bucket_prefix", "face_index", "label", "note", "updated_at_utc"]
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for tag in self._data.values():
                writer.writerow(
                    {
                        "face_id": tag.face_id,
                        "bucket_prefix": tag.bucket_prefix,
                        "face_index": tag.face_index,
                        "label": tag.label,
                        "note": tag.note,
                        "updated_at_utc": tag.updated_at_utc,
                    }
                )
