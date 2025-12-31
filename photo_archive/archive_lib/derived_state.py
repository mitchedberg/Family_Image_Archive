"""Helpers for tracking whether derived web assets need to be regenerated."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from .sidecar import BucketSidecar, write_sidecar


def mark_buckets_dirty(
    buckets_dir: Path,
    *,
    prefixes: Iterable[str],
    reason: Optional[str] = None,
) -> int:
    """Mark provided bucket prefixes as needing derived rebuilds."""
    updated = 0
    timestamp = datetime.now(timezone.utc).isoformat()
    for prefix in prefixes:
        sidecar_path = buckets_dir / f"bkt_{prefix}" / "sidecar.json"
        if not sidecar_path.exists():
            continue
        try:
            payload = json.loads(sidecar_path.read_text())
        except json.JSONDecodeError:
            continue
        data = payload.setdefault("data", {})
        state = data.setdefault("derived_state", {})
        state["dirty"] = True
        state["dirty_reason"] = reason or "manual"
        state["dirty_at"] = timestamp
        bucket_id = payload.get("bucket_id", "")
        source = payload.get("source", "")
        write_sidecar(sidecar_path, BucketSidecar(bucket_id=bucket_id, source=source, data=data))
        updated += 1
    return updated
