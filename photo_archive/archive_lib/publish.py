"""Publishing logic for exporting preferred bucket variants."""
from __future__ import annotations

import csv
import datetime
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from PIL import Image

from .config import AppConfig
from . import hashing
from .reporting import BucketInfo, load_bucket_infos
from .ingest.assigner import AI_FRONT, PROXY_FRONT, RAW_FRONT, BUCKET_PREFIX_LENGTH
from .variant_selector import build_variant_index, select_variant as _select_variant_base


@dataclass
class PublishSummary:
    published: int
    skipped: Dict[str, int]
    relpaths: List[str]

PUBLISHED_FILENAME_TEMPLATE = "bkt_{prefix}__preferred.jpg"
JPEG_QUALITY = 90


def select_variant(
    info: BucketInfo,
    prefer_ai: bool,
    include_ai_only: bool,
) -> Tuple[Optional[Dict[str, object]], Optional[str]]:
    """Select best variant from bucket info.

    This wrapper preserves publish.py's include_ai_only logic while using
    the centralized variant selection utility.
    """
    variants_by_role = build_variant_index(info.variants)
    has_proxy = PROXY_FRONT in variants_by_role
    has_raw = RAW_FRONT in variants_by_role
    has_ai = AI_FRONT in variants_by_role
    ai_only = not (has_proxy or has_raw) and has_ai

    # Handle explicit preferred variant override
    if info.preferred_variant:
        variant = _select_variant_base(info.variants, preferred_role=info.preferred_variant)
        if variant:
            return variant, None

    # Handle ai_only filtering
    if ai_only and not include_ai_only:
        return None, "ai_only"

    # Use centralized selection with appropriate preference
    variant = _select_variant_base(info.variants, prefer_ai=prefer_ai)

    # Apply include_ai_only constraints
    if variant:
        role = variant.get("role")
        # If we got AI but shouldn't include AI-only, check if it's truly ai_only
        if role == AI_FRONT and not include_ai_only and ai_only:
            return None, "ai_only"
        return variant, None

    # If centralized selector found nothing, check if we should include AI-only as last resort
    if has_ai and include_ai_only:
        return variants_by_role.get(AI_FRONT), None

    return None, "no_variant"


class Publisher:
    def __init__(
        self,
        cfg: AppConfig,
        conn,
        *,
        logger: logging.Logger,
        prefer_ai: bool,
        include_ai_only: bool,
        keywords: bool,
        limit: Optional[int],
        bucket_prefix: Optional[str],
        prune: bool,
        dry_run: bool,
    ) -> None:
        self.cfg = cfg
        self.conn = conn
        self.logger = logger
        self.prefer_ai = prefer_ai
        self.include_ai_only = include_ai_only
        self.keywords = keywords
        self.limit = limit
        self.bucket_prefix = bucket_prefix
        self.prune = prune
        self.dry_run = dry_run
        self.published_root = cfg.staging_root / "03_PUBLISHED_TO_PHOTOS"
        self.tmp_root = self.published_root / "_tmp"
        if self.tmp_root.exists():
            shutil.rmtree(self.tmp_root)
        self.tmp_root.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.published_root / "published_manifest.csv"
        self._ensure_manifest_header()

    def run(self, *, source: str) -> PublishSummary:
        infos = load_bucket_infos(self.conn, self.cfg, source=source)
        produced_relpaths: List[str] = []
        published = 0
        skipped: Dict[str, int] = {}
        for info in infos:
            if self.bucket_prefix and info.bucket_prefix != self.bucket_prefix:
                continue
            if self.limit is not None and published >= self.limit:
                break
            variant, reason = select_variant(info, self.prefer_ai, self.include_ai_only)
            if not variant:
                skipped[reason or "unknown"] = skipped.get(reason or "unknown", 0) + 1
                if self.prune and not self.dry_run:
                    self._remove_published(info)
                continue
            relpath = self._publish_variant(info, variant)
            if relpath:
                produced_relpaths.append(relpath)
                published += 1
        if self.prune and not self.dry_run:
            self._prune(source, produced_relpaths)
        if not self.dry_run and self.tmp_root.exists():
            shutil.rmtree(self.tmp_root)
        self.logger.info("Published %d buckets (skipped=%s)", published, skipped)
        return PublishSummary(published=published, skipped=skipped, relpaths=produced_relpaths)

    def _publish_variant(self, info: BucketInfo, variant: Dict[str, object]) -> Optional[str]:
        prefix = info.bucket_prefix or info.bucket_id[:BUCKET_PREFIX_LENGTH]
        filename = PUBLISHED_FILENAME_TEMPLATE.format(prefix=prefix)
        relpath = str(Path(info.source) / filename)
        if self.dry_run:
            self.logger.info("Would publish %s from %s", relpath, variant["path"])
            return relpath
        final_path = self.published_root / relpath
        tmp_path = self.tmp_root / relpath
        tmp_path.parent.mkdir(parents=True, exist_ok=True)
        source_path = Path(variant["path"])
        if not source_path.exists():
            self.logger.error("Missing source file %s", source_path)
            return None
        self._write_output_image(source_path, tmp_path)
        output_sha = hashing.sha256_for_file(tmp_path)
        unchanged = False
        if final_path.exists():
            existing_sha = hashing.sha256_for_file(final_path)
            if existing_sha == output_sha:
                unchanged = True
                tmp_path.unlink()
            else:
                final_path.parent.mkdir(parents=True, exist_ok=True)
                os.replace(tmp_path, final_path)
        else:
            final_path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(tmp_path, final_path)
        if self.keywords:
            written = self._write_keywords(final_path, info)
        else:
            written = False
        self._append_manifest(
            info=info,
            variant=variant,
            relpath=relpath,
            output_sha=output_sha if not unchanged else hashing.sha256_for_file(final_path),
            keywords_written=int(written),
            notes="unchanged" if unchanged else "",
        )
        return relpath

    def _write_output_image(self, source: Path, target: Path) -> None:
        if source.suffix.lower() in {".jpg", ".jpeg"}:
            shutil.copy2(source, target)
            return
        with Image.open(source) as img:
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img.save(target, format="JPEG", quality=JPEG_QUALITY)

    def _write_keywords(self, file_path: Path, info: BucketInfo) -> bool:
        prefix = info.bucket_prefix or info.bucket_id[:BUCKET_PREFIX_LENGTH]
        keywords = [f"bucket:{prefix}", f"source:{info.source}"]
        if info.group_key:
            keywords.append(f"group:{info.group_key}")
        args = [
            "exiftool",
            "-overwrite_original",
        ]
        for i, keyword in enumerate(keywords):
            if i == 0:
                args.append(f"-keywords={keyword}")
            else:
                args.append(f"-keywords+={keyword}")
        args.append(str(file_path))
        try:
            result = subprocess.run(args, capture_output=True)
        except FileNotFoundError:
            self.logger.warning("ExifTool not found; skipping keywords for %s", file_path)
            return False
        if result.returncode != 0:
            self.logger.warning("ExifTool failed for %s: %s", file_path, result.stderr.decode().strip())
            return False
        return True

    def _append_manifest(
        self,
        *,
        info: BucketInfo,
        variant: Dict[str, object],
        relpath: str,
        output_sha: str,
        keywords_written: int,
        notes: str,
    ) -> None:
        with self.manifest_path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    datetime.datetime.utcnow().isoformat(),
                    info.source,
                    info.bucket_id,
                    info.bucket_prefix or info.bucket_id[:BUCKET_PREFIX_LENGTH],
                    info.group_key,
                    variant.get("role"),
                    variant.get("sha256"),
                    relpath,
                    output_sha,
                    keywords_written,
                    notes,
                ]
            )

    def _ensure_manifest_header(self) -> None:
        if self.manifest_path.exists():
            return
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with self.manifest_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "published_at",
                    "source",
                    "bucket_id",
                    "bucket_prefix",
                    "group_key",
                    "preferred_variant",
                    "input_sha256",
                    "output_relpath",
                    "output_sha256",
                    "keywords_written",
                    "notes",
                ]
            )

    def _remove_published(self, info: BucketInfo) -> None:
        prefix = info.bucket_prefix or info.bucket_id[:BUCKET_PREFIX_LENGTH]
        filename = PUBLISHED_FILENAME_TEMPLATE.format(prefix=prefix)
        final_path = self.published_root / info.source / filename
        if final_path.exists():
            final_path.unlink()

    def _prune(self, source: str, keep_relpaths: Sequence[str]) -> None:
        if self.limit is not None or self.bucket_prefix:
            return
        keep_set = {self.published_root / Path(rp) for rp in keep_relpaths}
        source_dir = self.published_root / source
        if not source_dir.exists():
            return
        for file_path in source_dir.glob("bkt_*.jpg"):
            if file_path not in keep_set:
                file_path.unlink()
