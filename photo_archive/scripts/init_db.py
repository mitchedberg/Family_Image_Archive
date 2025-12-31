"""Initialize archive SQLite database."""
from __future__ import annotations

import argparse
import logging

from archive_lib import config as config_mod
from archive_lib import db as db_mod

logger = logging.getLogger(__name__)


CREATE_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS files (
        sha256 TEXT PRIMARY KEY,
        path TEXT NOT NULL,
        size INTEGER NOT NULL,
        ext TEXT NOT NULL,
        width INTEGER,
        height INTEGER,
        mtime TEXT NOT NULL,
        mtime_epoch REAL,
        exif_datetime TEXT,
        source TEXT,
        original_relpath TEXT,
        original_filename TEXT,
        donor_path TEXT,
        staged_path TEXT,
        staged_at TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS buckets (
        bucket_id TEXT PRIMARY KEY,
        bucket_prefix TEXT NOT NULL,
        source TEXT,
        preferred_variant TEXT,
        cluster_id TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS bucket_files (
        bucket_id TEXT NOT NULL,
        file_sha256 TEXT NOT NULL,
        role TEXT NOT NULL,
        is_primary INTEGER DEFAULT 0,
        notes TEXT,
        PRIMARY KEY (bucket_id, role, file_sha256),
        FOREIGN KEY (bucket_id) REFERENCES buckets(bucket_id) ON DELETE CASCADE,
        FOREIGN KEY (file_sha256) REFERENCES files(sha256) ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS links (
        bucket_id_a TEXT NOT NULL,
        bucket_id_b TEXT NOT NULL,
        link_type TEXT NOT NULL,
        confidence REAL,
        PRIMARY KEY (bucket_id_a, bucket_id_b, link_type)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS runs (
        run_id INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at TEXT NOT NULL,
        root TEXT,
        source TEXT,
        dry_run INTEGER NOT NULL,
        counts_json TEXT
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_files_path ON files(path);",
    "CREATE INDEX IF NOT EXISTS idx_bucket_files_bucket ON bucket_files(bucket_id);",
    "CREATE INDEX IF NOT EXISTS idx_bucket_files_file ON bucket_files(file_sha256);",
    "CREATE INDEX IF NOT EXISTS idx_buckets_source ON buckets(source);",
    "CREATE INDEX IF NOT EXISTS idx_buckets_cluster ON buckets(cluster_id);",
    """
    CREATE TABLE IF NOT EXISTS pending_variants (
        file_sha256 TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        role TEXT NOT NULL,
        join_key TEXT,
        fastfoto_token TEXT,
        img_token TEXT,
        notes TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (file_sha256) REFERENCES files(sha256) ON DELETE CASCADE
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_pending_variants_source_key
    ON pending_variants(source, join_key);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_pending_variants_source_fastfoto
    ON pending_variants(source, fastfoto_token);
    """,
    """
    CREATE TABLE IF NOT EXISTS bucket_join_keys (
        bucket_id TEXT NOT NULL,
        source TEXT NOT NULL,
        key_type TEXT NOT NULL,
        key_value TEXT NOT NULL,
        PRIMARY KEY (source, key_type, key_value),
        FOREIGN KEY (bucket_id) REFERENCES buckets(bucket_id) ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS face_embeddings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bucket_id TEXT NOT NULL,
        file_sha256 TEXT NOT NULL,
        variant_role TEXT NOT NULL,
        face_index INTEGER NOT NULL,
        left REAL NOT NULL,
        top REAL NOT NULL,
        width REAL NOT NULL,
        height REAL NOT NULL,
        confidence REAL,
        embedding BLOB NOT NULL,
        embedding_dim INTEGER NOT NULL,
        landmarks TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (bucket_id) REFERENCES buckets(bucket_id) ON DELETE CASCADE,
        FOREIGN KEY (file_sha256) REFERENCES files(sha256) ON DELETE CASCADE
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_face_embeddings_bucket ON face_embeddings(bucket_id);",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_face_embeddings_bucket_role_face ON face_embeddings(bucket_id, variant_role, face_index);",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Initialize archive SQLite database")
    parser.add_argument(
        "--db",
        type=str,
        default=None,
        help="Path to archive.sqlite (defaults to staging 02_WORKING_BUCKETS/db)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        help="Logging level",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=args.log_level.upper(), format="%(levelname)s | %(message)s")
    cfg = config_mod.load_config(args.db)
    logger.info("Initializing DB at %s", cfg.db_path)
    conn = db_mod.connect(cfg.db_path)
    db_mod.execute_script(conn, CREATE_STATEMENTS)
    _ensure_files_columns(conn)
    _ensure_pending_columns(conn)
    logger.info("DB ready")


def _ensure_files_columns(conn) -> None:
    """Ensure legacy databases have staging-related columns."""
    required = {
        "mtime_epoch": "REAL",
        "donor_path": "TEXT",
        "staged_path": "TEXT",
        "staged_at": "TEXT",
    }
    cursor = conn.execute("PRAGMA table_info(files)")
    existing = {row[1] for row in cursor.fetchall()}
    cursor.close()
    for column, ddl in required.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE files ADD COLUMN {column} {ddl}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_files_donor_path ON files(donor_path)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_files_staged_path ON files(staged_path)")
    conn.commit()


def _ensure_pending_columns(conn) -> None:
    cursor = conn.execute("PRAGMA table_info(pending_variants)")
    columns = {row[1] for row in cursor.fetchall()}
    cursor.close()
    if "img_token" not in columns:
        conn.execute("ALTER TABLE pending_variants ADD COLUMN img_token TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pending_variants_source_img_token ON pending_variants(source, img_token)"
    )
    conn.commit()


if __name__ == "__main__":  # pragma: no cover
    main()
