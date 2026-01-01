"""Persist acceptance/rejection metadata for face matches."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from .base_stores import BaseCSVStore
from .label_utils import normalize_label


@dataclass
class FaceVote:
    face_id: str
    label: str
    verdict: str  # "accept" or "reject"
    note: str = ""
    updated_at_utc: str = ""


class FaceVoteStore(BaseCSVStore[FaceVote]):
    """CSV-backed storage for per-label per-face review decisions."""

    @property
    def fieldnames(self) -> List[str]:
        """Return CSV column names."""
        return ["face_id", "label", "verdict", "note", "updated_at_utc"]

    def _parse_row(self, row: Dict[str, str]) -> FaceVote | None:
        """Parse a CSV row into a FaceVote object."""
        face_id = (row.get("face_id") or "").strip()
        label = (row.get("label") or "").strip()
        normalized = normalize_label(label)
        verdict = (row.get("verdict") or "").strip().lower()
        if not face_id or not normalized or verdict not in {"accept", "reject"}:
            return None
        return FaceVote(
            face_id=face_id,
            label=label,
            verdict=verdict,
            note=row.get("note", "").strip(),
            updated_at_utc=row.get("updated_at_utc", ""),
        )

    def _row_dict(self, item: FaceVote) -> Dict[str, Any]:
        """Convert a FaceVote object to a CSV row dict."""
        return {
            "face_id": item.face_id,
            "label": item.label,
            "verdict": item.verdict,
            "note": item.note,
            "updated_at_utc": item.updated_at_utc,
        }

    def _get_key(self, item: FaceVote) -> Tuple[str, str]:
        """Return the key for storing the vote (face_id, normalized_label)."""
        return (item.face_id, normalize_label(item.label))

    def rejected_for(self, label: str) -> Set[str]:
        """Return set of face_ids that were rejected for a given label."""
        normalized = normalize_label(label)
        if not normalized:
            return set()
        return {
            face_id
            for (face_id, lbl), vote in self._data.items()
            if lbl == normalized and vote.verdict == "reject"
        }

    def record(self, face_id: str, label: str, verdict: str, note: str = "") -> FaceVote:
        """Record a vote for a face/label pair."""
        verdict = verdict.lower().strip()
        if verdict not in {"accept", "reject"}:
            raise ValueError("verdict must be 'accept' or 'reject'")
        clean_face = (face_id or "").strip()
        clean_label = (label or "").strip()
        normalized = normalize_label(label)
        if not clean_face or not normalized:
            raise ValueError("face_id and label are required")
        ts = datetime.now(timezone.utc).isoformat()
        vote = FaceVote(face_id=clean_face, label=clean_label, verdict=verdict, note=note.strip(), updated_at_utc=ts)
        key = (clean_face, normalized)
        with self.lock:
            self._data[key] = vote
            self._write()
        return vote

    def merge_labels(self, source_label: str, target_label: str) -> int:
        """Move every stored vote from source_label to target_label."""
        source_label = source_label.strip()
        target_label = target_label.strip()
        source_normalized = normalize_label(source_label)
        target_normalized = normalize_label(target_label)
        if (
            not source_label
            or not target_label
            or not source_normalized
            or not target_normalized
            or source_normalized == target_normalized
        ):
            return 0
        updated = 0
        timestamp = datetime.now(timezone.utc).isoformat()
        with self.lock:
            entries = list(self._data.items())
            for key, vote in entries:
                if key[1] != source_normalized:
                    continue
                updated += 1
                new_key = (vote.face_id, target_normalized)
                existing = self._data.get(new_key)
                if existing:
                    verdict = "accept" if "accept" in {existing.verdict, vote.verdict} else "reject"
                    note = existing.note or vote.note
                else:
                    verdict = vote.verdict
                    note = vote.note
                self._data[new_key] = FaceVote(
                    face_id=vote.face_id,
                    label=target_label,
                    verdict=verdict,
                    note=note,
                    updated_at_utc=timestamp,
                )
                del self._data[key]
            if updated:
                self._write()
        return updated

    def clear(self, face_id: str, label: str) -> bool:
        """Remove any stored vote for face_id/label."""
        face_key = (face_id or "").strip()
        label_key = normalize_label(label)
        if not face_key or not label_key:
            return False
        key = (face_key, label_key)
        with self.lock:
            if key not in self._data:
                return False
            del self._data[key]
            self._write()
        return True
