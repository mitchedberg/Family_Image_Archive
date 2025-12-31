"""CSV-backed store of face_ids we want to ignore entirely."""
from __future__ import annotations

import csv
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict


@dataclass
class FaceIgnore:
    face_id: str
    reason: str
    note: str = ""
    updated_at_utc: str = ""


class FaceIgnoreStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: Dict[str, FaceIgnore] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        with self.path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                face_id = (row.get("face_id") or "").strip()
                if not face_id:
                    continue
                self._data[face_id] = FaceIgnore(
                    face_id=face_id,
                    reason=(row.get("reason") or "").strip() or "unknown",
                    note=row.get("note", "").strip(),
                    updated_at_utc=row.get("updated_at_utc", ""),
                )

    def all(self) -> Dict[str, FaceIgnore]:
        return dict(self._data)

    def add(self, face_id: str, reason: str, note: str = "") -> FaceIgnore:
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
        face_id = face_id.strip()
        if not face_id:
            return False
        with self.lock:
            if face_id not in self._data:
                return False
            del self._data[face_id]
            self._write()
        return True

    def _write(self) -> None:
        with self.path.open("w", newline="", encoding="utf-8") as handle:
            fieldnames = ["face_id", "reason", "note", "updated_at_utc"]
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for ignore in self._data.values():
                writer.writerow(
                    {
                        "face_id": ignore.face_id,
                        "reason": ignore.reason,
                        "note": ignore.note,
                        "updated_at_utc": ignore.updated_at_utc,
                    }
                )
