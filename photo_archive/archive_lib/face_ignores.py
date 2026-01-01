"""CSV-backed store of face_ids we want to ignore entirely."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from .base_stores import BaseCSVStore


@dataclass
class FaceIgnore:
    face_id: str
    reason: str
    note: str = ""
    updated_at_utc: str = ""


class FaceIgnoreStore(BaseCSVStore[FaceIgnore]):
    """CSV-backed store of face_ids we want to ignore entirely."""

    @property
    def fieldnames(self) -> List[str]:
        """Return CSV column names."""
        return ["face_id", "reason", "note", "updated_at_utc"]

    def _parse_row(self, row: Dict[str, str]) -> FaceIgnore | None:
        """Parse a CSV row into a FaceIgnore object."""
        face_id = (row.get("face_id") or "").strip()
        if not face_id:
            return None
        return FaceIgnore(
            face_id=face_id,
            reason=(row.get("reason") or "").strip() or "unknown",
            note=row.get("note", "").strip(),
            updated_at_utc=row.get("updated_at_utc", ""),
        )

    def _row_dict(self, item: FaceIgnore) -> Dict[str, Any]:
        """Convert a FaceIgnore object to a CSV row dict."""
        return {
            "face_id": item.face_id,
            "reason": item.reason,
            "note": item.note,
            "updated_at_utc": item.updated_at_utc,
        }

    def _get_key(self, item: FaceIgnore) -> str:
        """Return the key for storing the ignore entry (face_id)."""
        return item.face_id

    def add(self, face_id: str, reason: str, note: str = "") -> FaceIgnore:
        """Add a face to the ignore list."""
        face_id = face_id.strip()
        if not face_id:
            raise ValueError("face_id is required")
        timestamp = datetime.now(timezone.utc).isoformat()
        ignore = FaceIgnore(face_id=face_id, reason=reason.strip() or "unknown", note=note.strip(), updated_at_utc=timestamp)
        with self.lock:
            self._data[face_id] = ignore
            self._write()
        return ignore

    def remove(self, face_id: str) -> bool:
        """Remove a face from the ignore list."""
        face_id = face_id.strip()
        if not face_id:
            return False
        with self.lock:
            if face_id not in self._data:
                return False
            del self._data[face_id]
            self._write()
        return True
