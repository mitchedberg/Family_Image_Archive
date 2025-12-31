"""Utilities for forward-only negatives hard identity workflow."""
from __future__ import annotations

import csv
import logging
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from PIL import Image

from . import hashing
from .config import AppConfig
from .db import connect
from .derived_state import mark_buckets_dirty
from .ingest.assigner import extract_img_token

NEGATIVES_SUBDIR_CUT = "Negatives Cut"
NEGATIVES_SUBDIR_INPUT = "Negatives_Input"
NEGATIVES_SUBDIR_OUTPUT = "Negatives_Output"
REPORTS_SUBDIR = "02_WORKING_BUCKETS/reports"

CUT_TO_INPUT_MANIFEST = "cut_to_input_manifest.csv"
AI_JOB_MANIFEST = "ai_job_manifest.csv"
AI_OUTPUTS_UNMAPPED = "ai_outputs_unmapped.csv"

CUT_TO_INPUT_HEADER = [
    "run_id",
    "source",
    "bucket_prefix",
    "cut_path",
    "cut_sha256",
    "img_token",
    "input_path",
    "input_sha256",
    "created_at_utc",
]

AI_JOB_HEADER = [
    "run_id",
    "source",
    "bucket_prefix",
    "img_token",
    "input_path",
    "input_sha256",
    "expected_output_basename",
    "output_path",
    "output_sha256",
    "created_at_utc",
    "notes",
]

UNMAPPED_HEADER = [
    "run_id",
    "bucket_prefix",
    "img_token",
    "reason",
    "candidates",
]

INPUT_IMG_FORMAT = "JPEG"
JPEG_QUALITY = 90
IMAGE_EXTENSIONS = {".tif", ".tiff", ".jpg", ".jpeg", ".png"}
BUCKET_LABEL = "bkt_"


@dataclass(frozen=True)
class NegativePaths:
    cut_root: Path
    input_root: Path
    output_root: Path
    reports_dir: Path
    strip_root: Optional[Path] = None


@dataclass(frozen=True)
class StripReclassifyResult:
    bucket_count: int
    file_count: int


@dataclass
class ProxyCloneRepairSummary:
    source: str
    duplicate_groups: int
    buckets_removed: int
    join_keys_reassigned: int
    dry_run: bool


def resolve_paths(
    *,
    staged_root: Optional[Path],
    cut_root: Optional[Path],
    input_root: Optional[Path],
    output_root: Optional[Path],
    reports_dir: Optional[Path],
) -> NegativePaths:
    """Resolve staged-root derived defaults with explicit overrides."""
    base = staged_root
    derived_cut = base / NEGATIVES_SUBDIR_CUT if base else None
    derived_input = base / NEGATIVES_SUBDIR_INPUT if base else None
    derived_output = base / NEGATIVES_SUBDIR_OUTPUT if base else None
    derived_reports = base / REPORTS_SUBDIR if base else None

    final_cut = Path(cut_root).expanduser() if cut_root else derived_cut
    final_input = Path(input_root).expanduser() if input_root else derived_input
    final_output = Path(output_root).expanduser() if output_root else derived_output
    final_reports = Path(reports_dir).expanduser() if reports_dir else derived_reports

    missing: List[str] = []
    for label, path in (
        ("cut_root", final_cut),
        ("input_root", final_input),
        ("output_root", final_output),
        ("reports_dir", final_reports),
    ):
        if path is None:
            missing.append(
                f"{label} (derived path missing; pass --{label.replace('_', '-')})"
            )
        elif not path.exists() or not path.is_dir():
            missing.append(
                f"{label}={path} does not exist; create it or override with --{label.replace('_', '-')}"
            )
    if missing:
        raise ValueError("Path resolution failed:\n" + "\n".join(f"  - {msg}" for msg in missing))

    return NegativePaths(
        cut_root=final_cut,
        input_root=final_input,
        output_root=final_output,
        reports_dir=final_reports,
    )


def default_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def ensure_reports_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _chunked(items: Sequence[str], size: int = 200) -> Iterable[Sequence[str]]:
    for idx in range(0, len(items), size):
        yield items[idx : idx + size]


def load_manifest(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader)


def append_manifest_rows(path: Path, header: Sequence[str], rows: Iterable[Sequence[str]]) -> None:
    exists = path.exists()
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        if not exists:
            writer.writerow(header)
        writer.writerows(rows)


def rewrite_manifest(path: Path, header: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def gather_bucket_mapping(
    cfg: AppConfig,
    *,
    source: str,
    logger: logging.Logger,
) -> Dict[Path, Dict[str, str]]:
    """Return mapping of staged path -> bucket/basics for canonical files."""
    conn = connect(cfg.db_path)
    cursor = conn.execute(
        """
        SELECT f.staged_path, f.path, f.sha256, f.original_filename,
               b.bucket_id, b.bucket_prefix
        FROM files f
        JOIN bucket_files bf ON bf.file_sha256 = f.sha256
        JOIN buckets b ON b.bucket_id = bf.bucket_id
        WHERE b.source = ?
          AND bf.role IN ('raw_front', 'proxy_front')
        """,
        (source,),
    )
    mapping: Dict[Path, Dict[str, str]] = {}
    for row in cursor.fetchall():
        staged = row["staged_path"] or row["path"]
        if not staged:
            continue
        mapping[Path(staged)] = {
            "bucket_id": row["bucket_id"],
            "bucket_prefix": row["bucket_prefix"],
            "img_token": extract_img_token(row["original_filename"]),
            "sha256": row["sha256"],
        }
    cursor.close()
    logger.info("Loaded %d canonical file mappings for %s", len(mapping), source)
    return mapping


def render_input_name(bucket_prefix: str, img_token: Optional[str]) -> str:
    suffix = img_token or "noimg"
    prefix_core = bucket_prefix[4:] if bucket_prefix.startswith(BUCKET_LABEL) else bucket_prefix
    return f"{BUCKET_LABEL}{prefix_core}__{suffix}__input.jpg"


def render_output_name(bucket_prefix: str, img_token: Optional[str]) -> str:
    suffix = img_token or "noimg"
    prefix_core = bucket_prefix[4:] if bucket_prefix.startswith(BUCKET_LABEL) else bucket_prefix
    return f"{BUCKET_LABEL}{prefix_core}__{suffix}__ai_v1.png"


def _latest_run_id(rows: Sequence[Dict[str, str]]) -> Optional[str]:
    if not rows:
        return None
    # choose last chronological by created_at
    sorted_rows = sorted(rows, key=lambda r: r.get("created_at_utc", ""))
    return sorted_rows[-1]["run_id"]


def plan_ai_job(
    paths: NegativePaths,
    *,
    source: str,
    input_run_id: Optional[str],
    run_id: Optional[str],
    logger: logging.Logger,
) -> Tuple[str, int]:
    """Create ai_job_manifest entries from cut_to_input manifest."""
    ensure_reports_dir(paths.reports_dir)
    cut_manifest_path = paths.reports_dir / CUT_TO_INPUT_MANIFEST
    rows = load_manifest(cut_manifest_path)
    if not rows:
        raise ValueError(f"No rows found in {cut_manifest_path}; run export_inputs first.")
    target_input_run = input_run_id or _latest_run_id(rows)
    if not target_input_run:
        raise ValueError("Unable to determine input run_id for AI job planning.")
    filtered = [row for row in rows if row.get("run_id") == target_input_run]
    if not filtered:
        raise ValueError(f"No cut_to_input_manifest rows found for run_id={target_input_run}")

    job_manifest_path = paths.reports_dir / AI_JOB_MANIFEST
    existing_jobs = load_manifest(job_manifest_path)
    existing_keys = {(row["run_id"], row["bucket_prefix"]) for row in existing_jobs}

    timestamp = datetime.now(timezone.utc).isoformat()
    ai_run_id = run_id or default_run_id()
    appended: List[List[str]] = []
    for row in filtered:
        bucket_prefix = row.get("bucket_prefix", "")
        key = (ai_run_id, bucket_prefix)
        if key in existing_keys:
            continue
        img_token = row.get("img_token") or extract_img_token(row.get("cut_path"))
        expected = render_output_name(bucket_prefix, img_token)
        appended.append(
            [
                ai_run_id,
                source,
                bucket_prefix,
                img_token or "",
                row.get("input_path", ""),
                row.get("input_sha256", ""),
                expected,
                "",
                "",
                timestamp,
                "",
            ]
        )

    if appended:
        append_manifest_rows(job_manifest_path, AI_JOB_HEADER, appended)
    logger.info(
        "Planned AI job for input_run_id=%s output_run_id=%s | %d entries added",
        target_input_run,
        ai_run_id,
        len(appended),
    )
    return ai_run_id, len(appended)


def dicts_to_rows(rows: Sequence[Dict[str, str]], header: Sequence[str]) -> List[List[str]]:
    return [[row.get(col, "") for col in header] for row in rows]


def rename_outputs(
    paths: NegativePaths,
    *,
    run_id: str,
    dry_run: bool,
    logger: logging.Logger,
) -> Tuple[int, int]:
    """Rename AI outputs for the provided run_id using the job manifest."""
    ensure_reports_dir(paths.reports_dir)
    job_manifest_path = paths.reports_dir / AI_JOB_MANIFEST
    job_rows = load_manifest(job_manifest_path)
    if not job_rows:
        raise ValueError(f"No job manifest entries found at {job_manifest_path}")

    target_rows = [row for row in job_rows if row["run_id"] == run_id]
    if not target_rows:
        raise ValueError(f"No ai_job_manifest entries for run_id={run_id}")

    renamed = 0
    planned = 0
    unmapped: List[List[str]] = []
    used_sources: set[Path] = set()

    for row in target_rows:
        expected_name = row["expected_output_basename"]
        expected_path = paths.output_root / expected_name
        token = row["img_token"]

        if expected_path.exists():
            if not dry_run:
                row["output_path"] = str(expected_path)
                row["output_sha256"] = hashing.sha256_for_file(expected_path)
            continue

        candidates: List[Path] = []
        if token:
            candidates = [
                path
                for path in paths.output_root.glob(f"*{token}*")
                if path.is_file() and not path.name.startswith("bkt_")
            ]
        if dry_run:
            if len(candidates) == 1:
                planned += 1
            elif len(candidates) != 1:
                reason = "no_match" if not candidates else "multiple_matches"
                unmapped.append([run_id, row["bucket_prefix"], token or "", reason, ";".join(p.name for p in candidates)])
            continue

        # Apply rename
        candidates = [path for path in candidates if path not in used_sources]
        if len(candidates) == 1:
            src = candidates[0]
            used_sources.add(src)
            expected_path.parent.mkdir(parents=True, exist_ok=True)
            src.rename(expected_path)
            row["output_path"] = str(expected_path)
            row["output_sha256"] = hashing.sha256_for_file(expected_path)
            row["notes"] = ""
            renamed += 1
        else:
            reason = "no_match" if not candidates else "multiple_matches"
            unmapped.append([run_id, row["bucket_prefix"], token or "", reason, ";".join(p.name for p in candidates)])
            if not row.get("notes"):
                row["notes"] = reason

    if dry_run:
        logger.info("Dry-run rename: %d files would be renamed, %d unmapped", planned, len(unmapped))
        return planned, len(unmapped)

    # Rewrite manifest with updated rows
    rewrite_manifest(job_manifest_path, AI_JOB_HEADER, dicts_to_rows(job_rows, AI_JOB_HEADER))
    if unmapped:
        unmapped_path = paths.reports_dir / AI_OUTPUTS_UNMAPPED
        rewrite_manifest(unmapped_path, UNMAPPED_HEADER, unmapped)
    logger.info("Renamed %d AI outputs (%d unmapped) for run_id=%s", renamed, len(unmapped), run_id)
    return renamed, len(unmapped)


def export_inputs(
    cfg: AppConfig,
    paths: NegativePaths,
    *,
    source: str,
    run_id: str,
    prefix_len: int,
    logger: logging.Logger,
) -> Tuple[int, int]:
    """Convert Negatives Cut originals into JPEG inputs with manifest logging."""
    ensure_reports_dir(paths.reports_dir)
    manifest_path = paths.reports_dir / CUT_TO_INPUT_MANIFEST
    existing_rows = load_manifest(manifest_path)
    seen_cut_shas = {row["cut_sha256"] for row in existing_rows}
    mapping = gather_bucket_mapping(cfg, source=source, logger=logger)
    paths.input_root.mkdir(parents=True, exist_ok=True)

    appended: List[List[str]] = []
    skipped = 0
    created = 0
    timestamp = datetime.now(timezone.utc).isoformat()

    for file_path in sorted(paths.cut_root.rglob("*")):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        info = mapping.get(file_path)
        if not info:
            logger.debug("No bucket mapping for %s", file_path)
            continue
        cut_sha = hashing.sha256_for_file(file_path)
        if cut_sha in seen_cut_shas:
            skipped += 1
            continue
        bucket_prefix = info["bucket_prefix"][:prefix_len]
        img_token = info["img_token"]
        dest_name = render_input_name(bucket_prefix, img_token)
        dest_path = paths.input_root / dest_name
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(file_path) as img:
            rgb = img.convert("RGB")
            rgb.save(dest_path, INPUT_IMG_FORMAT, quality=JPEG_QUALITY, optimize=True)
        input_sha = hashing.sha256_for_file(dest_path)
        appended.append(
            [
                run_id,
                source,
                bucket_prefix,
                str(file_path),
                cut_sha,
                img_token or "",
                str(dest_path),
                input_sha,
                timestamp,
            ]
        )
        seen_cut_shas.add(cut_sha)
        created += 1

    if appended:
        append_manifest_rows(manifest_path, CUT_TO_INPUT_HEADER, appended)
    logger.info(
        "Exported %d inputs (skipped %d already exported) | run_id=%s",
        created,
        skipped,
        run_id,
    )
    return created, skipped


def repair_proxy_clones(
    conn: sqlite3.Connection,
    cfg: AppConfig,
    *,
    source: str,
    logger: logging.Logger,
    dry_run: bool = False,
) -> ProxyCloneRepairSummary:
    dup_rows = conn.execute(
        """
        WITH dup_sha AS (
            SELECT bf.file_sha256
            FROM bucket_files bf
            JOIN buckets b ON b.bucket_id = bf.bucket_id
            WHERE b.source = ? AND bf.role = 'proxy_front'
            GROUP BY bf.file_sha256
            HAVING COUNT(*) > 1
        )
        SELECT
            d.file_sha256,
            b.bucket_id,
            b.bucket_prefix,
            EXISTS (
                SELECT 1 FROM bucket_files bf2
                WHERE bf2.bucket_id = b.bucket_id AND bf2.role = 'raw_front'
            ) AS has_raw
        FROM bucket_files bf
        JOIN buckets b ON b.bucket_id = bf.bucket_id
        JOIN dup_sha d ON d.file_sha256 = bf.file_sha256
        WHERE bf.role = 'proxy_front'
        ORDER BY d.file_sha256, has_raw DESC
        """,
        (source,),
    ).fetchall()
    if not dup_rows:
        return ProxyCloneRepairSummary(source=source, duplicate_groups=0, buckets_removed=0, join_keys_reassigned=0, dry_run=dry_run)

    groups: Dict[str, List[sqlite3.Row]] = {}
    for row in dup_rows:
        groups.setdefault(row["file_sha256"], []).append(row)

    duplicate_groups = 0
    buckets_removed = 0
    join_keys_reassigned = 0

    dirty_prefixes: List[str] = []
    for file_sha, rows in groups.items():
        canonical = next((row for row in rows if row["has_raw"]), None)
        if not canonical:
            logger.warning("No raw bucket for proxy sha %s; skipping", file_sha[:12])
            continue
        clones = [row for row in rows if row["bucket_id"] != canonical["bucket_id"]]
        if not clones:
            continue
        duplicate_groups += 1
        logger.info(
            "Merging %d proxy clones for %s into %s",
            len(clones),
            file_sha[:12],
            canonical["bucket_prefix"],
        )
        if dry_run:
            buckets_removed += len(clones)
            continue
        canonical_id = canonical["bucket_id"]
        for clone in clones:
            clone_id = clone["bucket_id"]
            cursor = conn.execute(
                "UPDATE bucket_join_keys SET bucket_id = ? WHERE bucket_id = ?",
                (canonical_id, clone_id),
            )
            join_keys_reassigned += cursor.rowcount or 0
            conn.execute("DELETE FROM buckets WHERE bucket_id = ?", (clone_id,))
            bucket_dir = cfg.buckets_dir / f"bkt_{clone['bucket_prefix']}"
            if bucket_dir.exists():
                shutil.rmtree(bucket_dir)
        buckets_removed += len(clones)
        dirty_prefixes.append(canonical["bucket_prefix"])
    if not dry_run:
        conn.commit()
        if dirty_prefixes:
            mark_buckets_dirty(cfg.buckets_dir, prefixes=dirty_prefixes, reason="proxy_clone_merge")
    return ProxyCloneRepairSummary(
        source=source,
        duplicate_groups=duplicate_groups,
        buckets_removed=buckets_removed,
        join_keys_reassigned=join_keys_reassigned,
        dry_run=dry_run,
    )
