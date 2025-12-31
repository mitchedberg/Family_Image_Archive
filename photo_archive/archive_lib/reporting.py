"""Reporting utilities for bucket health and coverage."""
from __future__ import annotations

import csv
import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .config import AppConfig
from .ingest.assigner import AI_FRONT, RAW_FRONT, PROXY_FRONT, BUCKET_PREFIX_LENGTH

HEX_PREFIX_RE = re.compile(r"(?i)\b[a-f0-9]{8,64}\b")


@dataclass
class BucketInfo:
    bucket_id: str
    bucket_prefix: str
    source: str
    group_key: str
    roles: Dict[str, int]
    needs_review: bool
    needs_review_reasons: Sequence[str]
    variants: Sequence[Dict[str, object]]
    preferred_variant: Optional[str]
    data: Dict[str, object]

    def front_count(self) -> int:
        return self.roles.get(RAW_FRONT, 0) + self.roles.get(PROXY_FRONT, 0)

    def ai_count(self) -> int:
        return self.roles.get(AI_FRONT, 0)

    def variant_count(self) -> int:
        return len(self.variants)


@dataclass
class ReportSummary:
    total_buckets: int
    role_presence: Dict[str, int]
    needs_review_count: int
    ai_only_count: int
    missing_canonical_count: int
    multi_front_count: int
    no_join_key_count: int
    ai_orphans_count: int
    unassigned_count: int
    top_group_keys: List[Tuple[str, int]] = field(default_factory=list)


def load_bucket_infos(conn: sqlite3.Connection, cfg: AppConfig, *, source: Optional[str] = None) -> List[BucketInfo]:
    query = "SELECT bucket_id, bucket_prefix, source, preferred_variant FROM buckets"
    params: List[object] = []
    if source:
        query += " WHERE source = ?"
        params.append(source)
    cursor = conn.execute(query, params)
    rows = cursor.fetchall()
    cursor.close()
    infos: List[BucketInfo] = []
    for row in rows:
        bucket_id = row["bucket_id"]
        dir_path = cfg.buckets_dir / f"bkt_{bucket_id[:BUCKET_PREFIX_LENGTH]}"
        sidecar_path = dir_path / "sidecar.json"
        if not sidecar_path.exists():
            continue
        with sidecar_path.open("r", encoding="utf-8") as handle:
            sidecar = json.load(handle)
        data = sidecar.get("data", {})
        variants = data.get("variants", [])
        roles: Dict[str, int] = {}
        for variant in variants:
            role = variant.get("role") or "unknown"
            roles[role] = roles.get(role, 0) + 1
        infos.append(
            BucketInfo(
                bucket_id=bucket_id,
                bucket_prefix=row["bucket_prefix"],
                source=row["source"],
                group_key=data.get("group_key", ""),
                roles=roles,
                needs_review=bool(data.get("needs_review")),
                needs_review_reasons=data.get("needs_review_reasons", []),
                variants=variants,
                preferred_variant=row["preferred_variant"],
                data=data,
            )
        )
    return infos


def generate_report(
    conn: sqlite3.Connection,
    cfg: AppConfig,
    *,
    source: Optional[str] = None,
    logger: Optional[logging.Logger] = None,
) -> ReportSummary:
    infos = load_bucket_infos(conn, cfg, source=source)
    total = len(infos)
    role_presence: Dict[str, int] = {}
    ai_only_rows: List[BucketInfo] = []
    missing_canonical: List[BucketInfo] = []
    multi_front: List[BucketInfo] = []
    no_join_key: List[BucketInfo] = []
    needs_review_rows: List[BucketInfo] = []
    group_hist: Dict[str, int] = {}

    for info in infos:
        for role, count in info.roles.items():
            if count > 0:
                role_presence[role] = role_presence.get(role, 0) + 1
        front_count = info.front_count()
        ai_count = info.ai_count()
        if info.needs_review:
            needs_review_rows.append(info)
        if front_count == 0 and ai_count > 0:
            ai_only_rows.append(info)
        if front_count == 0:
            missing_canonical.append(info)
        if front_count > 1:
            multi_front.append(info)
        if not _has_join_key(info):
            no_join_key.append(info)
        group_hist[info.group_key] = group_hist.get(info.group_key, 0) + info.variant_count()

    ai_orphans = _unassigned_files(conn, role_filter="ai")
    unassigned = _unassigned_files(conn)

    _write_bucket_csv(cfg.reports_dir / "needs_review_buckets.csv", needs_review_rows)
    _write_bucket_csv(cfg.reports_dir / "ai_only_buckets.csv", ai_only_rows)
    _write_bucket_csv(cfg.reports_dir / "missing_canonical_front.csv", missing_canonical)
    _write_bucket_csv(cfg.reports_dir / "multi_front_buckets.csv", multi_front)
    _write_bucket_csv(cfg.reports_dir / "no_join_key_buckets.csv", no_join_key)
    _write_file_csv(cfg.reports_dir / "ai_orphans.csv", ai_orphans)
    _write_file_csv(cfg.reports_dir / "unassigned_files.csv", unassigned)

    top_groups = sorted(group_hist.items(), key=lambda item: item[1], reverse=True)[:20]

    return ReportSummary(
        total_buckets=total,
        role_presence=role_presence,
        needs_review_count=len(needs_review_rows),
        ai_only_count=len(ai_only_rows),
        missing_canonical_count=len(missing_canonical),
        multi_front_count=len(multi_front),
        no_join_key_count=len(no_join_key),
        ai_orphans_count=len(ai_orphans),
        unassigned_count=len(unassigned),
        top_group_keys=top_groups,
    )


def _has_join_key(info: BucketInfo) -> bool:
    group_key = info.group_key or ""
    if group_key.lower().startswith("fastfoto_"):
        return True
    for variant in info.variants:
        filename = (variant.get("original_filename") or "").lower()
        if HEX_PREFIX_RE.search(filename):
            return True
    return False


def _write_bucket_csv(path: Path, rows: Sequence[BucketInfo]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["bucket_id", "source", "group_key", "roles", "needs_review", "reasons"])
        for info in rows:
            writer.writerow(
                [
                    info.bucket_id,
                    info.source,
                    info.group_key,
                    json.dumps(info.roles),
                    int(info.needs_review),
                    ";".join(info.needs_review_reasons),
                ]
            )


def _unassigned_files(conn: sqlite3.Connection, role_filter: Optional[str] = None) -> List[sqlite3.Row]:
    query = """
        SELECT f.*
        FROM files f
        LEFT JOIN bucket_files bf ON bf.file_sha256 = f.sha256
        WHERE bf.bucket_id IS NULL
    """
    rows = conn.execute(query).fetchall()
    if role_filter == "ai":
        return [row for row in rows if _looks_like_ai(row)]
    return rows


def _looks_like_ai(row: sqlite3.Row) -> bool:
    name = (row["original_filename"] or "").lower()
    relpath = (row["original_relpath"] or "").lower()
    if "pro_4k" in name or "ai" in name:
        return True
    if relpath.endswith(".png") and "output" in relpath:
        return True
    return False


def _write_file_csv(path: Path, rows: Sequence[sqlite3.Row]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["sha256", "path", "original_relpath", "source", "original_filename"])
        for row in rows:
            writer.writerow(
                [
                    row["sha256"],
                    row["path"],
                    row["original_relpath"],
                    row["source"],
                    row["original_filename"],
                ]
            )
