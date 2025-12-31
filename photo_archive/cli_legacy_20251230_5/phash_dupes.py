"""Generate perceptual hashes for bucket fronts (test-only diagnostic)."""
from __future__ import annotations

import csv
import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

import cv2  # type: ignore
import numpy as np
import typer
from PIL import Image, UnidentifiedImageError
from tqdm import tqdm

from archive_lib import config as config_mod, log as log_mod
from archive_lib.reporting import BucketInfo, load_bucket_infos

app = typer.Typer(add_completion=False)

FRONT_ROLES = ("raw_front", "proxy_front")
DERIVED_WEB_NAME = "web_front.jpg"
DERIVED_THUMB = "thumb_front.jpg"
REPORT_ROOT_NAME = "phash_test"
DEFAULT_THRESHOLD = 8
BIN_PREFIX_CHARS = 4  # 16 bits


@dataclass
class HashRecord:
    bucket_prefix: str
    source: str
    role: str
    image_path: Path
    phash_hex: str


@dataclass
class RunStats:
    total_buckets: int = 0
    processed: int = 0
    skipped_no_front: int = 0
    skipped_missing_file: int = 0
    skipped_errors: int = 0
    skipped_back_only: int = 0


@app.command()
def main(
    source: Optional[List[str]] = typer.Option(None, "--source", help="Limit to these source labels"),
    threshold: int = typer.Option(DEFAULT_THRESHOLD, "--threshold", min=0, max=64, help="Hamming distance threshold"),
    limit: int = typer.Option(0, "--limit", help="Max buckets to process (0 = no limit)"),
    preview: int = typer.Option(0, "--preview", help="Process only the first N buckets (deterministic)"),
    run_id: Optional[str] = typer.Option(None, "--run-id", help="Custom run identifier"),
    use_web_front: bool = typer.Option(True, "--use-web-front/--no-web-front", help="Prefer derived web_front.jpg when available"),
    db_readonly: bool = typer.Option(True, "--db-readonly/--db-writable", help="Open archive DB read-only"),
    dry_run: bool = typer.Option(True, "--dry-run/--apply", help="If apply, write CSV/JSON reports"),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging verbosity"),
) -> None:
    if not db_readonly:
        raise typer.BadParameter("This command only supports read-only DB access.")

    log_mod.setup_logging(log_level)
    logger = logging.getLogger("cli.phash_dupes")

    cfg = config_mod.load_config()
    conn = _connect_db(cfg)
    infos = load_bucket_infos(conn, cfg)
    conn.close()

    if source:
        allowed = set(source)
        infos = [info for info in infos if info.source in allowed]

    infos = sorted(infos, key=lambda item: (item.source or "", item.bucket_prefix))
    back_skip_prefixes = _detect_family_back_prefixes(infos)
    if preview > 0:
        infos = infos[:preview]
    elif limit > 0:
        infos = infos[:limit]

    if not infos:
        typer.echo("No buckets found for the requested filters.")
        raise typer.Exit(code=1)

    run_identifier = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_root = cfg.reports_dir / REPORT_ROOT_NAME / run_identifier

    stats = RunStats(total_buckets=len(infos))
    hash_records: List[HashRecord] = []
    errors: List[str] = []

    progress = tqdm(infos, unit="bucket")
    for info in progress:
        progress.set_description(f"bkt_{info.bucket_prefix}")
        if info.bucket_prefix in back_skip_prefixes:
            stats.skipped_back_only += 1
            continue
        try:
            record = _hash_bucket(cfg, info, use_web_front)
        except FileNotFoundError:
            stats.skipped_missing_file += 1
            continue
        except Exception as exc:  # pragma: no cover - best effort logging
            stats.skipped_errors += 1
            errors.append(f"{info.bucket_prefix}: {exc}")
            logger.warning("Failed hashing %s: %s", info.bucket_prefix, exc)
            continue
        if record is None:
            stats.skipped_no_front += 1
            continue
        hash_records.append(record)
        stats.processed += 1

    duplicates = _find_duplicates(hash_records, threshold)
    typer.echo(
        f"Buckets processed: {stats.processed}/{stats.total_buckets} · duplicates found: {len(duplicates)}"
    )
    if stats.skipped_back_only:
        typer.echo(f"Skipped {stats.skipped_back_only} FastFoto backs (family_photos).")

    if dry_run:
        typer.echo("Dry-run complete; no files written.")
        return

    _write_reports(report_root, hash_records, duplicates, stats, threshold, use_web_front, source or [], errors)
    typer.echo(f"Reports written to {report_root}")


def _connect_db(cfg: config_mod.AppConfig):
    uri = f"file:{cfg.db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _detect_family_back_prefixes(infos: Sequence[BucketInfo]) -> Set[str]:
    """Return bucket prefixes that correspond to Family Photos backs."""
    skip: Set[str] = set()
    for info in infos:
        if (info.source or "").lower() != "family_photos":
            continue
        original = _family_photos_original(info)
        if original and _looks_like_fastfoto_back(original):
            skip.add(info.bucket_prefix)
    return skip


def _family_photos_original(info: BucketInfo) -> str:
    data = info.data if isinstance(info.data, dict) else {}
    photos_asset = data.get("photos_asset")
    if not isinstance(photos_asset, dict):
        return ""
    return str(photos_asset.get("original_filename") or "")


def _looks_like_fastfoto_back(name: str) -> bool:
    lower = name.lower()
    if not lower.startswith("fastfoto"):
        return False
    stem = lower.rsplit(".", 1)[0]
    return stem.endswith("_b")


def _hash_bucket(cfg: config_mod.AppConfig, info: BucketInfo, use_web_front: bool) -> Optional[HashRecord]:
    variant_map = _variant_index(info.variants)
    chosen_variant = None
    chosen_role = None
    for role in FRONT_ROLES:
        candidate = variant_map.get(role)
        if candidate:
            chosen_variant = candidate
            chosen_role = role
            break
    if not chosen_variant or not chosen_role:
        return None

    bucket_dir = cfg.buckets_dir / f"bkt_{info.bucket_prefix}"
    image_path: Optional[Path] = None
    if use_web_front:
        derived = bucket_dir / "derived" / DERIVED_WEB_NAME
        if derived.exists():
            image_path = derived
    if image_path is None:
        variant_path = _variant_path(chosen_variant)
        if not variant_path or not variant_path.exists():
            raise FileNotFoundError(f"Front source missing for bucket {info.bucket_prefix}")
        image_path = variant_path

    phash_hex = _compute_phash(image_path)
    return HashRecord(
        bucket_prefix=info.bucket_prefix,
        source=info.source or "",
        role=chosen_role,
        image_path=image_path,
        phash_hex=phash_hex,
    )


def _variant_index(variants) -> Dict[str, dict]:
    index: Dict[str, dict] = {}
    for variant in variants or []:
        role = variant.get("role") if isinstance(variant, dict) else getattr(variant, "role", None)
        if role and role not in index:
            index[role] = variant
    return index


def _variant_path(variant) -> Optional[Path]:
    if isinstance(variant, dict):
        path_value = variant.get("path")
    else:
        path_value = getattr(variant, "path", None)
    if not path_value:
        return None
    return Path(str(path_value))


def _compute_phash(image_path: Path) -> str:
    try:
        with Image.open(image_path) as img:
            img = img.convert("L")
            img = img.resize((32, 32), Image.LANCZOS)
            pixels = np.array(img, dtype=np.float32)
    except (UnidentifiedImageError, OSError) as exc:
        raise RuntimeError(f"Failed to open {image_path}: {exc}") from exc

    dct = cv2.dct(pixels)
    block = dct[:8, :8]
    flatten = block.flatten()
    median = np.median(flatten[1:]) if flatten.size > 1 else np.median(flatten)
    bits = (flatten > median).astype(np.uint8)
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return f"{value:016x}"  # 64-bit hex


def _find_duplicates(records: Sequence[HashRecord], threshold: int) -> List[Tuple[HashRecord, HashRecord, int]]:
    results: List[Tuple[HashRecord, HashRecord, int]] = []
    if len(records) <= 2000:
        candidates = [(i, j) for i in range(len(records)) for j in range(i + 1, len(records))]
    else:
        bins: Dict[str, List[int]] = {}
        for idx, rec in enumerate(records):
            key = rec.phash_hex[:BIN_PREFIX_CHARS]
            bins.setdefault(key, []).append(idx)
        candidates = []
        for entries in bins.values():
            if len(entries) < 2:
                continue
            for i in range(len(entries)):
                for j in range(i + 1, len(entries)):
                    candidates.append((entries[i], entries[j]))
    for i, j in candidates:
        rec_a = records[i]
        rec_b = records[j]
        dist = _hamming_distance(rec_a.phash_hex, rec_b.phash_hex)
        if dist <= threshold:
            results.append((rec_a, rec_b, dist))
    return results


def _hamming_distance(hex_a: str, hex_b: str) -> int:
    a = int(hex_a, 16)
    b = int(hex_b, 16)
    diff = a ^ b
    return diff.bit_count() if hasattr(diff, "bit_count") else bin(diff).count("1")


def _write_reports(
    report_root: Path,
    records: Sequence[HashRecord],
    duplicates: Sequence[Tuple[HashRecord, HashRecord, int]],
    stats: RunStats,
    threshold: int,
    use_web_front: bool,
    sources: Sequence[str],
    errors: Sequence[str],
) -> None:
    os.makedirs(report_root, exist_ok=True)
    fronts_csv = report_root / "phash_fronts.csv"
    dupes_csv = report_root / "near_duplicates.csv"
    summary_json = report_root / "phash_run_summary.json"

    with fronts_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["bucket_prefix", "source", "chosen_role", "image_path", "phash_hex"])
        for rec in records:
            writer.writerow([
                rec.bucket_prefix,
                rec.source,
                rec.role,
                str(rec.image_path),
                rec.phash_hex,
            ])

    with dupes_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["bucket_prefix_a", "bucket_prefix_b", "distance", "reason"])
        for rec_a, rec_b, dist in duplicates:
            writer.writerow([
                rec_a.bucket_prefix,
                rec_b.bucket_prefix,
                dist,
                f"phash<= {threshold}",
            ])

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "threshold": threshold,
        "sources": sources,
        "use_web_front": use_web_front,
        "bucket_total": stats.total_buckets,
        "processed": stats.processed,
        "skipped": {
            "no_front": stats.skipped_no_front,
            "missing_file": stats.skipped_missing_file,
            "errors": stats.skipped_errors,
            "family_back": stats.skipped_back_only,
        },
        "records_written": len(records),
        "duplicate_pairs": len(duplicates),
        "errors": list(errors),
    }
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")


if __name__ == "__main__":  # pragma: no cover
    app()
