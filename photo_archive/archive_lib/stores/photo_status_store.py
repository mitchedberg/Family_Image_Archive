"""Store for tracking per-photo (bucket) status like done."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

from .json_store import BaseJSONStore


class PhotoStatusStore(BaseJSONStore):
    """Track per-photo (bucket) status like done.

    Manages completion status for photo buckets, tracking when they were
    marked done and by whom. This helps users track their progress through
    the photo tagging workflow.

    Thread-safe with atomic file writes.
    """

    VERSION = 1

    def _init_data(self) -> Dict[str, object]:
        """Initialize data structure with photos dict."""
        return {
            "version": self.VERSION,
            "updated_at": int(time.time()),
            "photos": {},
        }

    def _load(self) -> None:
        """Load and validate photo status from JSON file."""
        if not self.path.exists():
            return
        try:
            import json
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}

        # Validate and load photos
        photos = payload.get("photos")
        if isinstance(photos, dict):
            self._data["photos"] = photos

        # Update version if valid
        version = payload.get("version")
        if isinstance(version, int) and version > 0:
            self._data["version"] = version

        # Update timestamp if valid
        updated = payload.get("updated_at")
        if isinstance(updated, (int, float)):
            self._data["updated_at"] = int(updated)

    def get(self, bucket_prefix: str) -> Dict[str, object]:
        """Get status entry for a bucket.

        Args:
            bucket_prefix: Bucket identifier

        Returns:
            Dictionary with status information (done, done_at, done_by)
        """
        if not bucket_prefix:
            return {}
        entry = self._data.get("photos", {}).get(bucket_prefix)
        if isinstance(entry, dict):
            return dict(entry)
        return {}

    def is_done(self, bucket_prefix: str) -> bool:
        """Check if a bucket is marked as done.

        Args:
            bucket_prefix: Bucket identifier

        Returns:
            True if bucket is marked done, False otherwise
        """
        entry = self.get(bucket_prefix)
        return bool(entry.get("done"))

    def set_done(self, bucket_prefix: str, done: bool, done_by: str = "") -> Dict[str, object]:
        """Set done status for a bucket.

        Args:
            bucket_prefix: Bucket identifier
            done: Whether bucket is done
            done_by: Optional username who marked it done

        Returns:
            Updated status entry

        Raises:
            ValueError: If bucket_prefix is empty
        """
        clean_bucket = (bucket_prefix or "").strip()
        if not clean_bucket:
            raise ValueError("bucket_prefix is required")
        clean_by = (done_by or "").strip()

        with self.lock:
            photos = self._data.setdefault("photos", {})
            if not done:
                # Remove entry when unmarking as done
                photos.pop(clean_bucket, None)
                self._touch_locked()
                self._write_locked()
                return {"bucket_prefix": clean_bucket, "done": False}

            # Mark as done with timestamp
            entry = photos.get(clean_bucket)
            if not isinstance(entry, dict):
                entry = {}
                photos[clean_bucket] = entry
            entry["done"] = True
            entry["done_at"] = datetime.now(timezone.utc).isoformat()
            if clean_by:
                entry["done_by"] = clean_by
            self._touch_locked()
            self._write_locked()
            return {"bucket_prefix": clean_bucket, **entry}

    def done_buckets(self) -> set[str]:
        """Get set of all bucket prefixes marked as done.

        Returns:
            Set of bucket prefix strings
        """
        photos = self._data.get("photos", {})
        if not isinstance(photos, dict):
            return set()
        return {bucket for bucket, entry in photos.items() if isinstance(entry, dict) and entry.get("done")}
