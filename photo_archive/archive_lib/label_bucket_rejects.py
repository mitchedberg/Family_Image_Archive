"""CSV-backed store for bucket-level rejects per person label."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from .base_stores import BaseCSVStore
from .label_utils import normalize_label


@dataclass
class LabelBucketReject:
    label: str
    bucket_prefix: str
    updated_at_utc: str = ""


class LabelBucketRejectStore(BaseCSVStore[LabelBucketReject]):
    """Persist (label, bucket_prefix) rejects so queues can skip them."""

    @property
    def fieldnames(self) -> List[str]:
        """Return CSV column names."""
        return ["label", "bucket_prefix", "updated_at_utc"]

    def _parse_row(self, row: Dict[str, str]) -> LabelBucketReject | None:
        """Parse a CSV row into a LabelBucketReject object."""
        label = (row.get("label") or "").strip()
        normalized = normalize_label(label)
        bucket_prefix = (row.get("bucket_prefix") or "").strip()
        ts = (row.get("updated_at_utc") or "").strip()
        if not normalized or not bucket_prefix:
            return None
        return LabelBucketReject(
            label=label,
            bucket_prefix=bucket_prefix,
            updated_at_utc=ts,
        )

    def _row_dict(self, item: LabelBucketReject) -> Dict[str, Any]:
        """Convert a LabelBucketReject object to a CSV row dict."""
        return {
            "label": item.label,
            "bucket_prefix": item.bucket_prefix,
            "updated_at_utc": item.updated_at_utc,
        }

    def _get_key(self, item: LabelBucketReject) -> Tuple[str, str]:
        """Return the key for storing the reject (normalized_label, bucket_prefix)."""
        return (normalize_label(item.label), item.bucket_prefix)

    def rejected_buckets_for(self, label: str) -> Set[str]:
        """Return set of bucket_prefixes rejected for a given label."""
        normalized = normalize_label(label)
        if not normalized:
            return set()
        return {bucket for (lbl, bucket) in self._data if lbl == normalized}

    def add(self, label: str, bucket_prefix: str) -> Dict[str, str]:
        """Add a label/bucket reject."""
        clean_bucket = (bucket_prefix or "").strip()
        clean_label = (label or "").strip()
        normalized = normalize_label(clean_label)
        if not clean_bucket or not normalized:
            raise ValueError("label and bucket_prefix are required")
        reject = LabelBucketReject(
            label=clean_label,
            bucket_prefix=clean_bucket,
            updated_at_utc=datetime.now(timezone.utc).isoformat(),
        )
        key = (normalized, clean_bucket)
        with self.lock:
            self._data[key] = reject
            self._write()
        return {
            "label": reject.label,
            "bucket_prefix": reject.bucket_prefix,
            "updated_at_utc": reject.updated_at_utc,
        }

    def remove(self, label: str, bucket_prefix: str) -> bool:
        """Remove a label/bucket reject."""
        normalized = normalize_label(label)
        clean_bucket = (bucket_prefix or "").strip()
        if not normalized or not clean_bucket:
            return False
        key = (normalized, clean_bucket)
        with self.lock:
            if key not in self._data:
                return False
            del self._data[key]
            self._write()
            return True

    def list_for(self, label: str) -> List[Dict[str, str]]:
        """List all rejects for a given label."""
        normalized = normalize_label(label)
        if not normalized:
            return []
        return [
            {
                "label": reject.label,
                "bucket_prefix": reject.bucket_prefix,
                "updated_at_utc": reject.updated_at_utc,
            }
            for (lbl, _), reject in self._data.items()
            if lbl == normalized
        ]

    def all(self) -> List[Dict[str, str]]:
        """Return all rejects as a list of dicts."""
        return [
            {
                "label": reject.label,
                "bucket_prefix": reject.bucket_prefix,
                "updated_at_utc": reject.updated_at_utc,
            }
            for reject in self._data.values()
        ]
