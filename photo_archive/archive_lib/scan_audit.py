"""Audit utilities for face scan coverage."""
from __future__ import annotations

import csv
import logging
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional

from .config import AppConfig


def audit_face_coverage(
    conn: sqlite3.Connection,
    cfg: AppConfig,
    logger: Optional[logging.Logger] = None,
) -> Path:
    """Generate a CSV report of face detection coverage per bucket."""
    
    # 1. Get all buckets known to the DB
    bucket_rows = conn.execute("SELECT bucket_id, bucket_prefix, source FROM buckets").fetchall()
    db_buckets = {row["bucket_id"]: dict(row) for row in bucket_rows}
    
    # 2. Get face statistics
    face_stats = {}
    cursor = conn.execute("""
        SELECT 
            bucket_id,
            COUNT(*) as face_count,
            MAX(confidence) as max_conf,
            MIN(confidence) as min_conf
        FROM face_embeddings
        WHERE embedding IS NOT NULL
        GROUP BY bucket_id
    """)
    for row in cursor:
        face_stats[row["bucket_id"]] = {
            "face_count": row["face_count"],
            "max_conf": row["max_conf"],
            "min_conf": row["min_conf"],
        }
    cursor.close()

    # 3. Scan disk for actual buckets (to catch zombies)
    disk_buckets = set()
    if cfg.buckets_dir.exists():
        for item in cfg.buckets_dir.iterdir():
            if item.is_dir() and item.name.startswith("bkt_"):
                # derived from folder name: bkt_prefix... but prefix length varies?
                # Actually usually bkt_<uuid> or bkt_<prefix>. 
                # Let's just track the folder name for cross-ref.
                disk_buckets.add(item.name)

    # 4. Merge and build report
    report_rows = []
    
    # Process DB buckets
    for bucket_id, info in db_buckets.items():
        stats = face_stats.get(bucket_id, {"face_count": 0, "max_conf": 0.0, "min_conf": 0.0})
        folder_name = f"bkt_{info['bucket_prefix']}" # Approximation, might not match exactly if prefix logic changed
        
        # Check if folder exists
        on_disk = False
        # Try exact prefix match first
        if (cfg.buckets_dir / folder_name).exists():
            on_disk = True
        else:
            # Fallback: check if any folder starts with this prefix? 
            # Or just rely on bucket_id if that's how folders are named.
            # Current convention seems to be bkt_<prefix>
            pass

        report_rows.append({
            "bucket_prefix": info["bucket_prefix"],
            "bucket_id": bucket_id,
            "source": info["source"],
            "on_disk": on_disk,
            "face_count": stats["face_count"],
            "max_conf": stats["max_conf"],
            "min_conf": stats["min_conf"],
            "status": "has_faces" if stats["face_count"] > 0 else "zero_faces"
        })

    # 5. Write Report
    out_path = cfg.reports_dir / "face_scan_coverage.csv"
    cfg.reports_dir.mkdir(parents=True, exist_ok=True)
    
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "bucket_prefix", "source", "face_count", "max_conf", "min_conf", "status", "bucket_id", "on_disk"
        ])
        writer.writeheader()
        for row in report_rows:
            writer.writerow(row)
            
    if logger:
        logger.info(f"Wrote coverage report to {out_path}")
        
    return out_path
