"""Generate reports for missing AI variants and orphaned AI files."""
from __future__ import annotations

import csv
import re
from pathlib import Path

from archive_lib import config as config_mod, db as db_mod

AI_PATH_PATTERNS = [
    ("Negatives_Output", "negatives"),
    ("Greg Scan/Output", "uncle"),
    ("Judy Photo Box/Processed", "judy"),
    ("Dad_Slides", "dad_slides"),
    ("family_photos_ai", "family_photos"),
    ("Mom_Photos", "family_photos"),
]

FASTFOTO_RE = re.compile(r"(\\d{16})")
PRO4K_RE = re.compile(r"PRO_4K_([^_/]+)")


def infer_source(path: str) -> str:
    for needle, source in AI_PATH_PATTERNS:
        if needle in path:
            return source
    return "unknown"


def write_missing_ai_buckets(conn, cfg) -> Path:
    output_dir = cfg.reports_dir / "ai_audit"
    output_dir.mkdir(parents=True, exist_ok=True)
    dest = output_dir / "missing_ai_buckets.csv"
    rows = conn.execute(
        """
        SELECT b.bucket_prefix,
               b.source,
               k.key_value AS fastfoto_hash,
               raw.path AS raw_path,
               proxy.path AS proxy_path
        FROM buckets b
        LEFT JOIN bucket_join_keys k
            ON k.bucket_id = b.bucket_id AND k.key_type = 'fastfoto_hash'
        LEFT JOIN bucket_files bf_raw
            ON bf_raw.bucket_id = b.bucket_id AND bf_raw.role = 'raw_front'
        LEFT JOIN files raw
            ON raw.sha256 = bf_raw.file_sha256
        LEFT JOIN bucket_files bf_proxy
            ON bf_proxy.bucket_id = b.bucket_id AND bf_proxy.role = 'proxy_front'
        LEFT JOIN files proxy
            ON proxy.sha256 = bf_proxy.file_sha256
        WHERE NOT EXISTS (
            SELECT 1 FROM bucket_files bf_ai
            WHERE bf_ai.bucket_id = b.bucket_id AND bf_ai.role = 'ai_front_v1'
        )
        ORDER BY b.source, b.bucket_prefix
        """
    ).fetchall()
    with dest.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["bucket_prefix", "source", "fastfoto_hash", "raw_path", "proxy_path"]
        )
        for row in rows:
            writer.writerow(
                [
                    row["bucket_prefix"],
                    row["source"],
                    row["fastfoto_hash"] or "",
                    row["raw_path"] or "",
                    row["proxy_path"] or "",
                ]
            )
    return dest


def write_orphan_ai_files(conn, cfg) -> Path:
    output_dir = cfg.reports_dir / "ai_audit"
    output_dir.mkdir(parents=True, exist_ok=True)
    dest = output_dir / "orphan_ai_outputs.csv"
    rows = conn.execute(
        """
        SELECT f.path, f.original_filename
        FROM files f
        LEFT JOIN bucket_files bf
            ON bf.file_sha256 = f.sha256 AND bf.role = 'ai_front_v1'
        WHERE bf.bucket_id IS NULL
          AND f.path LIKE '%PRO_4K_%'
        ORDER BY f.path
        """
    ).fetchall()
    with dest.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["path", "inferred_source", "fastfoto_hash", "filename"])
        for row in rows:
            path = row["path"] or ""
            filename = row["original_filename"] or Path(path).name
            match = FASTFOTO_RE.search(filename)
            fast_hash = match.group(1) if match else ""
            writer.writerow(
                [path, infer_source(path), fast_hash, filename]
            )
    return dest


def main() -> None:
    cfg = config_mod.load_config()
    conn = db_mod.connect(cfg.db_path)
    missing_path = write_missing_ai_buckets(conn, cfg)
    orphan_path = write_orphan_ai_files(conn, cfg)
    print(f"Wrote missing bucket report to {missing_path}")
    print(f"Wrote orphan AI report to {orphan_path}")


if __name__ == "__main__":
    main()
