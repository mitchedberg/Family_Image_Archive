"""Thumbnail generation for bucket variants."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional

from PIL import Image

from .config import AppConfig
from .ingest.assigner import BUCKET_PREFIX_LENGTH

THUMB_WIDTH = 768
THUMB_QUALITY = 85
THUMB_NAMES = {
    "front": "thumb_front.jpg",
    "proxy_front": "thumb_proxy_front.jpg",
    "ai_front_v1": "thumb_ai_front_v1.jpg",
    "back": "thumb_back.jpg",
}


class Thumbnailer:
    def __init__(self, cfg: AppConfig, *, logger: logging.Logger, force: bool = False) -> None:
        self.cfg = cfg
        self.logger = logger
        self.force = force

    def generate(self, bucket_id: str, variants: List[Dict[str, object]]) -> None:
        bucket_dir = self.cfg.buckets_dir / f"bkt_{bucket_id[:BUCKET_PREFIX_LENGTH]}"
        derived_dir = bucket_dir / "derived"
        derived_dir.mkdir(exist_ok=True)
        variant_map = _index_variants(variants)
        tasks = {
            "front": _select_display_front(variant_map),
            "proxy_front": variant_map.get("proxy_front"),
            "ai_front_v1": variant_map.get("ai_front_v1"),
            "back": _select_back(variant_map),
        }
        for key, variant in tasks.items():
            if not variant:
                continue
            target = derived_dir / THUMB_NAMES[key]
            source_path = Path(variant["path"])
            if not source_path.exists():
                self.logger.warning("Missing source for %s: %s", key, source_path)
                continue
            if target.exists() and not self.force:
                continue
            try:
                _write_thumb(source_path, target)
            except Exception as exc:  # pragma: no cover
                self.logger.error("Failed to create thumb for %s: %s", source_path, exc)


def _index_variants(variants: List[Dict[str, object]]) -> Dict[str, Dict[str, object]]:
    best: Dict[str, Dict[str, object]] = {}
    for variant in variants:
        role = variant.get("role")
        if role and role not in best:
            best[role] = variant
    return best


def _select_display_front(variant_map: Dict[str, Dict[str, object]]) -> Optional[Dict[str, object]]:
    return (
        variant_map.get("raw_front")
        or variant_map.get("proxy_front")
    )


def _select_back(variant_map: Dict[str, Dict[str, object]]) -> Optional[Dict[str, object]]:
    return variant_map.get("proxy_back") or variant_map.get("raw_back")


def _write_thumb(source: Path, target: Path) -> None:
    with Image.open(source) as img:
        img.thumbnail((THUMB_WIDTH, THUMB_WIDTH), Image.Resampling.LANCZOS)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        target.parent.mkdir(parents=True, exist_ok=True)
        img.save(target, format="JPEG", quality=THUMB_QUALITY)
