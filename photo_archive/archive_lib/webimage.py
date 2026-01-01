"""Helpers for generating medium-resolution review images."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Optional, Sequence

from PIL import Image

from .ingest.assigner import BUCKET_PREFIX_LENGTH
from .orientation import OrientationInfo, ensure_display_orientation, extract_orientation_info
from .sidecar import BucketSidecar, write_sidecar
from .variant_selector import build_variant_index

DEFAULT_WIDTH = 1600
DEFAULT_QUALITY = 85


def ensure_web_images(
    buckets: Sequence[Dict[str, object]] | Sequence[object],
    buckets_dir: Path,
    *,
    logger: logging.Logger,
    force: bool = False,
    dirty_only: bool = False,
    update_state: bool = False,
) -> Dict[str, int]:
    """Ensure each bucket has derived/web_front.jpg + web_ai.jpg.

    Returns counters so callers can log progress.
    """

    counts = {"created": 0, "skipped": 0, "missing_source": 0, "clean": 0}
    for info in buckets:
        bucket_id = info["bucket_id"] if isinstance(info, dict) else info.bucket_id
        bucket_prefix = (
            (info["bucket_prefix"] if isinstance(info, dict) else getattr(info, "bucket_prefix", None))
            or bucket_id[:BUCKET_PREFIX_LENGTH]
        )
        source = info["source"] if isinstance(info, dict) else getattr(info, "source", "")
        derived_dir = buckets_dir / f"bkt_{bucket_prefix}" / "derived"
        derived_dir.mkdir(parents=True, exist_ok=True)

        variants = info["variants"] if isinstance(info, dict) else info.variants
        data = (info.get("data") if isinstance(info, dict) else getattr(info, "data", None)) or {}
        variant_map = build_variant_index(variants)
        orientation_info = extract_orientation_info(info)
        state = dict(data.get("derived_state") or {})
        dirty_flag = bool(state.get("dirty"))
        now = datetime.now(timezone.utc).isoformat()
        sidecar_changed = False
        bucket_dir = buckets_dir / f"bkt_{bucket_prefix}"
        needs_any = False
        tasks = (
            (
                "web_front.jpg",
                variant_map.get("raw_front") or variant_map.get("proxy_front"),
                orientation_info,
                "raw_front_sha",
            ),
            ("web_ai.jpg", variant_map.get("ai_front_v1"), None, "ai_front_sha"),
            ("web_back.jpg", variant_map.get("proxy_back") or variant_map.get("raw_back"), None, "back_sha"),
        )
        for filename, variant, orient, state_key in tasks:
            if not variant:
                continue
            source_path = Path(str(variant.get("path", "")))
            if not source_path.exists():
                counts["missing_source"] += 1
                logger.debug("Missing source for %s: %s", filename, source_path)
                continue
            target_path = derived_dir / filename
            variant_sha = variant.get("sha256")
            stored_sha = state.get(state_key)
            needs_variant = (
                force
                or dirty_flag
                or not target_path.exists()
                or (variant_sha and stored_sha != variant_sha)
            )
            if not needs_variant:
                counts["skipped"] += 1
                continue
            try:
                _write_resized(source_path, target_path, orientation_info=orient)
            except Exception as exc:  # pragma: no cover
                counts["missing_source"] += 1
                logger.warning("Failed to build %s for %s: %s", filename, bucket_id, exc)
            else:
                counts["created"] += 1
                needs_any = True
                if update_state and data is not None:
                    state[state_key] = variant_sha
                    state["updated_at"] = now
                    sidecar_changed = True
        if dirty_only and not needs_any and not force:
            counts["clean"] += 1
            continue
        if update_state and data is not None:
            if needs_any:
                state["dirty"] = False
                state.pop("dirty_reason", None)
                state["cleared_at"] = now
                sidecar_changed = True
            if sidecar_changed:
                data["derived_state"] = state
                payload = BucketSidecar(bucket_id=bucket_id, source=source, data=data)
                sidecar_path = bucket_dir / "sidecar.json"
                write_sidecar(sidecar_path, payload)
    return counts


def _write_resized(
    source: Path,
    target: Path,
    *,
    width: int = DEFAULT_WIDTH,
    orientation_info: Optional[OrientationInfo] = None,
) -> None:
    with Image.open(source) as img:
        img = ensure_display_orientation(img, orientation_info)
        img.thumbnail((width, width), Image.Resampling.LANCZOS)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        target.parent.mkdir(parents=True, exist_ok=True)
        img.save(target, format="JPEG", quality=DEFAULT_QUALITY)
