"""Utility helpers for storing per-face labels."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from .base_stores import BaseCSVStore


@dataclass
class FaceTag:
    face_id: str
    bucket_prefix: str
    face_index: int
    label: str
    note: str = ""
    updated_at_utc: str = ""


class FaceTagStore(BaseCSVStore[FaceTag]):
    """Simple CSV-backed store for labeling detected faces."""

    @property
    def fieldnames(self) -> List[str]:
        """Return CSV column names."""
        return ["face_id", "bucket_prefix", "face_index", "label", "note", "updated_at_utc"]

    def _parse_row(self, row: Dict[str, str]) -> FaceTag | None:
        """Parse a CSV row into a FaceTag object."""
        face_id = (row.get("face_id") or "").strip()
        label = (row.get("label") or "").strip()
        if not face_id:
            return None
        try:
            face_index = int(row.get("face_index") or "0")
        except ValueError:
            face_index = 0
        return FaceTag(
            face_id=face_id,
            bucket_prefix=(row.get("bucket_prefix") or "").strip(),
            face_index=face_index,
            label=label,
            note=row.get("note", "").strip(),
            updated_at_utc=row.get("updated_at_utc", ""),
        )

    def _row_dict(self, item: FaceTag) -> Dict[str, Any]:
        """Convert a FaceTag object to a CSV row dict."""
        return {
            "face_id": item.face_id,
            "bucket_prefix": item.bucket_prefix,
            "face_index": item.face_index,
            "label": item.label,
            "note": item.note,
            "updated_at_utc": item.updated_at_utc,
        }

    def _get_key(self, item: FaceTag) -> str:
        """Return the key for storing the face tag (face_id)."""
        return item.face_id

    def update(self, face_id: str, bucket_prefix: str, face_index: int, label: str, note: str = "") -> FaceTag:
        """Update or create a face tag."""
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
        """Remove a face tag."""
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
