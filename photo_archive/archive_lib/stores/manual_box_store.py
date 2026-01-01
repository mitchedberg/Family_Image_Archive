"""Store for persisting manual face annotation boxes (non-destructive)."""
from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from .json_store import BaseJSONStore


def _normalize_manual_bbox(raw) -> Optional[Dict[str, float]]:
    """Normalize and validate a manual bounding box.

    Args:
        raw: Raw bbox dict with left/top/width/height

    Returns:
        Normalized bbox dict with values in [0,1] range, or None if invalid
    """
    if not isinstance(raw, dict):
        return None
    try:
        left = float(raw.get("left"))
        top = float(raw.get("top"))
        width = float(raw.get("width"))
        height = float(raw.get("height"))
    except (TypeError, ValueError):
        return None
    if any(value != value for value in (left, top, width, height)):
        return None
    left = max(0.0, min(1.0, left))
    top = max(0.0, min(1.0, top))
    width = max(0.0, min(1.0, width))
    height = max(0.0, min(1.0, height))
    if width <= 0 or height <= 0:
        return None
    if left + width > 1.0:
        width = max(0.0, 1.0 - left)
    if top + height > 1.0:
        height = max(0.0, 1.0 - top)
    if width <= 0 or height <= 0:
        return None
    return {"left": left, "top": top, "width": width, "height": height}


class ManualBoxStore(BaseJSONStore):
    """Persist manual face annotation boxes (non-destructive).

    Stores user-drawn bounding boxes for faces, allowing manual annotation
    of faces that weren't detected automatically. Each box can be assigned
    to a face index and labeled with a person's name.

    Thread-safe with atomic file writes.
    """

    VERSION = 1

    def _init_data(self) -> Dict[str, object]:
        """Initialize data structure with boxes dict."""
        return {
            "version": self.VERSION,
            "updated_at": int(time.time()),
            "boxes": {},
        }

    def _load(self) -> None:
        """Load and validate manual boxes from JSON file."""
        if not self.path.exists():
            return
        try:
            import json
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}

        # Validate and load boxes
        boxes = payload.get("boxes")
        if isinstance(boxes, dict):
            self._data["boxes"] = boxes

        # Update version if valid
        version = payload.get("version")
        if isinstance(version, int) and version > 0:
            self._data["version"] = version

        # Update timestamp if valid
        updated = payload.get("updated_at")
        if isinstance(updated, (int, float)):
            self._data["updated_at"] = int(updated)

    def list_boxes(self, bucket_prefix: str, side: Optional[str] = None) -> List[Dict[str, object]]:
        """List all manual boxes for a bucket, optionally filtered by side.

        Args:
            bucket_prefix: Bucket identifier
            side: Optional filter for "front" or "back"

        Returns:
            List of box dictionaries with id, side, bbox, label, face_index, timestamps
        """
        clean_bucket = (bucket_prefix or "").strip()
        if not clean_bucket:
            return []
        entries = self._data.get("boxes", {}).get(clean_bucket)
        if not isinstance(entries, list):
            return []
        normalized_side = (side or "").strip().lower()
        results: List[Dict[str, object]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if normalized_side and entry.get("side") != normalized_side:
                continue
            bbox = _normalize_manual_bbox(entry.get("bbox"))
            if not bbox:
                continue
            face_index = entry.get("face_index")
            if isinstance(face_index, (int, float)):
                face_index_value = int(face_index)
            else:
                face_index_value = None
            results.append(
                {
                    "id": entry.get("id"),
                    "side": entry.get("side") or "front",
                    "bbox": bbox,
                    "label": entry.get("label") or "",
                    "face_index": face_index_value,
                    "created_at": entry.get("created_at"),
                    "updated_at": entry.get("updated_at"),
                }
            )
        return results

    def add_box(
        self,
        bucket_prefix: str,
        side: str,
        bbox: Dict[str, float],
        *,
        face_index: Optional[int] = None,
    ) -> Dict[str, object]:
        """Add a new manual box.

        Args:
            bucket_prefix: Bucket identifier
            side: "front" or "back"
            bbox: Bounding box dict with left/top/width/height in [0,1]
            face_index: Optional face index to assign

        Returns:
            Created box entry

        Raises:
            ValueError: If bucket_prefix is empty, side is invalid, or bbox is invalid
        """
        clean_bucket = (bucket_prefix or "").strip()
        if not clean_bucket:
            raise ValueError("bucket_prefix is required")
        normalized_side = (side or "").strip().lower()
        if normalized_side not in {"front", "back"}:
            raise ValueError("side must be 'front' or 'back'")
        normalized_bbox = _normalize_manual_bbox(bbox)
        if not normalized_bbox:
            raise ValueError("bbox must include left/top/width/height between 0 and 1")
        face_index_value = int(face_index) if isinstance(face_index, (int, float)) else None
        entry = {
            "id": uuid.uuid4().hex,
            "side": normalized_side,
            "bbox": normalized_bbox,
            "label": "",
            "face_index": face_index_value,
            "created_at": int(time.time()),
            "updated_at": int(time.time()),
        }
        with self.lock:
            boxes = self._data.setdefault("boxes", {})
            rows = boxes.get(clean_bucket)
            if not isinstance(rows, list):
                rows = []
                boxes[clean_bucket] = rows
            rows.append(entry)
            self._touch_locked()
            self._write_locked()
        return entry

    def ensure_face_indices(
        self,
        bucket_prefix: str,
        start_index: int,
        used_indices: Optional[set[int]] = None,
    ) -> int:
        """Ensure all boxes have face indices assigned, avoiding conflicts.

        Args:
            bucket_prefix: Bucket identifier
            start_index: Minimum face index to use
            used_indices: Set of already-used face indices to avoid

        Returns:
            Next available face index after assignment
        """
        clean_bucket = (bucket_prefix or "").strip()
        if not clean_bucket:
            return start_index
        with self.lock:
            boxes = self._data.setdefault("boxes", {})
            rows = boxes.get(clean_bucket)
            if not isinstance(rows, list):
                return start_index
            used = set(used_indices or set())
            for entry in rows:
                if not isinstance(entry, dict):
                    continue
                face_index = entry.get("face_index")
                if isinstance(face_index, (int, float)):
                    used.add(int(face_index))
            base = max(used) + 1 if used else start_index
            next_index = max(start_index, base)
            changed = False
            for entry in rows:
                if not isinstance(entry, dict):
                    continue
                face_index = entry.get("face_index")
                if isinstance(face_index, (int, float)):
                    continue
                while next_index in used:
                    next_index += 1
                entry["face_index"] = next_index
                used.add(next_index)
                next_index += 1
                changed = True
            if changed:
                self._touch_locked()
                self._write_locked()
            return next_index

    def find_by_face_index(self, bucket_prefix: str, face_index: int) -> Optional[Dict[str, object]]:
        """Find a box by its face index.

        Args:
            bucket_prefix: Bucket identifier
            face_index: Face index to search for

        Returns:
            Box entry dict if found, None otherwise
        """
        clean_bucket = (bucket_prefix or "").strip()
        if not clean_bucket:
            return None
        entries = self._data.get("boxes", {}).get(clean_bucket)
        if not isinstance(entries, list):
            return None
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            stored = entry.get("face_index")
            if isinstance(stored, (int, float)) and int(stored) == face_index:
                return entry
        return None

    def update_label(self, bucket_prefix: str, box_id: str, label: str) -> Optional[Dict[str, object]]:
        """Update the label for a box.

        Args:
            bucket_prefix: Bucket identifier
            box_id: Box ID to update
            label: New label value

        Returns:
            Updated box entry if found, None otherwise

        Raises:
            ValueError: If bucket_prefix or box_id is empty
        """
        clean_bucket = (bucket_prefix or "").strip()
        clean_id = (box_id or "").strip()
        if not clean_bucket or not clean_id:
            raise ValueError("bucket_prefix and box_id are required")
        clean_label = (label or "").strip()
        with self.lock:
            boxes = self._data.setdefault("boxes", {})
            rows = boxes.get(clean_bucket)
            if not isinstance(rows, list):
                return None
            for entry in rows:
                if not isinstance(entry, dict):
                    continue
                if entry.get("id") != clean_id:
                    continue
                entry["label"] = clean_label
                entry["updated_at"] = int(time.time())
                self._touch_locked()
                self._write_locked()
                return {
                    "id": entry.get("id"),
                    "side": entry.get("side") or "front",
                    "bbox": _normalize_manual_bbox(entry.get("bbox")),
                    "label": entry.get("label") or "",
                    "created_at": entry.get("created_at"),
                    "updated_at": entry.get("updated_at"),
                }
        return None

    def remove_box(self, bucket_prefix: str, box_id: str) -> bool:
        """Remove a box by ID.

        Args:
            bucket_prefix: Bucket identifier
            box_id: Box ID to remove

        Returns:
            True if box was removed, False if not found

        Raises:
            ValueError: If bucket_prefix or box_id is empty
        """
        clean_bucket = (bucket_prefix or "").strip()
        clean_id = (box_id or "").strip()
        if not clean_bucket or not clean_id:
            raise ValueError("bucket_prefix and box_id are required")
        with self.lock:
            boxes = self._data.setdefault("boxes", {})
            rows = boxes.get(clean_bucket)
            if not isinstance(rows, list):
                return False
            initial = len(rows)
            boxes[clean_bucket] = [entry for entry in rows if entry.get("id") != clean_id]
            if len(boxes[clean_bucket]) == initial:
                return False
            if not boxes[clean_bucket]:
                boxes.pop(clean_bucket, None)
            self._touch_locked()
            self._write_locked()
            return True
