"""Repair utilities for archive maintenance."""
from __future__ import annotations

import logging
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .config import AppConfig
from .ingest.assigner import (
    AI_FRONT,
    BUCKET_PREFIX_LENGTH,
    compute_group_key,
    extract_fastfoto_token,
)


@dataclass
class RepairSummary:
    source: str
    buckets_considered: int
    buckets_removed: int
    variants_moved: int
    dry_run: bool


def move_ai_only_to_pending(
    conn: sqlite3.Connection,
    cfg: AppConfig,
    *,
    source: str,
    logger: logging.Logger,
    dry_run: bool = False,
) -> RepairSummary:
    rows = conn.execute(
        """
        SELECT b.bucket_id
        FROM buckets b
        WHERE b.source = ?
          AND NOT EXISTS (
            SELECT 1 FROM bucket_files bf
            WHERE bf.bucket_id = b.bucket_id AND bf.role IN ('raw_front', 'proxy_front')
          )
          AND EXISTS (
            SELECT 1 FROM bucket_files bf
            WHERE bf.bucket_id = b.bucket_id AND bf.role = ?
          )
        """,
        (source, AI_FRONT),
    ).fetchall()
    if not rows:
        return RepairSummary(source=source, buckets_considered=0, buckets_removed=0, variants_moved=0, dry_run=dry_run)

    timestamp = datetime.now(timezone.utc).isoformat()
    variants_moved = 0
    buckets_removed = 0
    for row in rows:
        bucket_id = row["bucket_id"]
        logger.info("Repairing AI-only bucket %s", bucket_id[:BUCKET_PREFIX_LENGTH])
        variants = conn.execute(
            """
            SELECT bf.file_sha256, bf.role, f.original_filename
            FROM bucket_files bf
            JOIN files f ON f.sha256 = bf.file_sha256
            WHERE bf.bucket_id = ?
            """,
            (bucket_id,),
        ).fetchall()
        for variant in variants:
            if variant["role"] != AI_FRONT:
                continue
            join_key = compute_group_key(variant["original_filename"])
            fastfoto = extract_fastfoto_token(variant["original_filename"])
            logger.debug("Queue pending %s", variant["file_sha256"])
            if dry_run:
                continue
            conn.execute(
                """
                INSERT INTO pending_variants (file_sha256, source, role, join_key, fastfoto_token, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(file_sha256) DO UPDATE SET
                    join_key=excluded.join_key,
                    fastfoto_token=excluded.fastfoto_token,
                    notes=excluded.notes
                """,
                (
                    variant["file_sha256"],
                    source,
                    variant["role"],
                    join_key,
                    fastfoto,
                    "repair_ai_only",
                    timestamp,
                ),
            )
            variants_moved += 1
        if dry_run:
            continue
        conn.execute("DELETE FROM bucket_files WHERE bucket_id = ?", (bucket_id,))
        conn.execute("DELETE FROM bucket_join_keys WHERE bucket_id = ?", (bucket_id,))
        conn.execute("DELETE FROM buckets WHERE bucket_id = ?", (bucket_id,))
        conn.commit()
        bucket_dir = cfg.buckets_dir / f"bkt_{bucket_id[:BUCKET_PREFIX_LENGTH]}"
        if bucket_dir.exists():
            shutil.rmtree(bucket_dir)
        buckets_removed += 1
    return RepairSummary(
        source=source,
        buckets_considered=len(rows),
        buckets_removed=buckets_removed,
        variants_moved=variants_moved,
        dry_run=dry_run,
    )
