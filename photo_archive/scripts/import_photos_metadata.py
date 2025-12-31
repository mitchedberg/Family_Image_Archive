"""Import osxphotos CSV metadata into archive DB."""
from __future__ import annotations

import argparse
import csv
import logging
from pathlib import Path

from archive_lib import config as config_mod, db as db_mod

logger = logging.getLogger(__name__)


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS photos_assets (
    uuid TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    file_sha256 TEXT,
    path TEXT NOT NULL,
    filename TEXT,
    original_filename TEXT,
    original_filesize INTEGER,
    uti_original TEXT,
    date TEXT,
    date_added TEXT,
    date_modified TEXT,
    hidden INTEGER,
    favorite INTEGER,
    has_adjustments INTEGER,
    adjustment_type INTEGER,
    orientation INTEGER,
    original_orientation INTEGER,
    width INTEGER,
    height INTEGER,
    original_width INTEGER,
    original_height INTEGER,
    keywords TEXT,
    albums TEXT,
    persons TEXT,
    face_count INTEGER,
    caption TEXT,
    description TEXT,
    title TEXT,
    latitude REAL,
    longitude REAL,
    place_name TEXT,
    import_uuid TEXT,
    FOREIGN KEY (file_sha256) REFERENCES files(sha256) ON DELETE SET NULL
);
"""

CREATE_INDEX_SQL = "CREATE INDEX IF NOT EXISTS idx_photos_assets_file ON photos_assets(file_sha256);"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import osxphotos CSV metadata into archive DB")
    parser.add_argument("--csv", required=True, type=Path, help="Path to osxphotos-exported CSV")
    parser.add_argument("--source", required=True, help="Source label (e.g., family_photos)")
    parser.add_argument("--db", type=Path, default=None, help="Path to archive.sqlite (optional)")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    return parser.parse_args()


def upsert_metadata(conn, csv_path: Path, source: str) -> tuple[int, int]:
    conn.execute(CREATE_TABLE_SQL)
    conn.execute(CREATE_INDEX_SQL)
    added = 0
    missing = 0
    with csv_path.open("r", newline="") as infile:
        reader = csv.DictReader(infile)
        rows = list(reader)
    for row in rows:
        path = row.get("path")
        uuid = row.get("uuid")
        if not path or not uuid:
            continue
        file_row = conn.execute(
            "SELECT sha256 FROM files WHERE path = ?", (path,)
        ).fetchone()
        if not file_row:
            missing += 1
            continue
        payload = {
            "uuid": uuid,
            "source": source,
            "file_sha256": file_row["sha256"],
            "path": path,
            "filename": row.get("filename"),
            "original_filename": row.get("original_filename"),
            "original_filesize": _to_int(row.get("original_filesize")),
            "uti_original": row.get("uti_original"),
            "date": row.get("date"),
            "date_added": row.get("date_added"),
            "date_modified": row.get("date_modified"),
            "hidden": _to_int(row.get("hidden")),
            "favorite": _to_int(row.get("favorite")),
            "has_adjustments": _to_int(row.get("hasadjustments") or row.get("has_adjustments")),
            "adjustment_type": _to_int(row.get("adjustment_type")),
            "orientation": _to_int(row.get("orientation")),
            "original_orientation": _to_int(row.get("original_orientation")),
            "width": _to_int(row.get("width")),
            "height": _to_int(row.get("height")),
            "original_width": _to_int(row.get("original_width")),
            "original_height": _to_int(row.get("original_height")),
            "keywords": row.get("keywords"),
            "albums": row.get("albums"),
            "persons": row.get("persons"),
            "face_count": _to_int(row.get("face_count")),
            "caption": row.get("caption"),
            "description": row.get("description"),
            "title": row.get("title"),
            "latitude": _to_float(row.get("location_latitude")),
            "longitude": _to_float(row.get("location_longitude")),
            "place_name": row.get("place_name"),
            "import_uuid": row.get("import_uuid"),
        }
        columns = ", ".join(payload.keys())
        placeholders = ", ".join([":" + key for key in payload.keys()])
        update_clause = ", ".join([f"{key}=excluded.{key}" for key in payload.keys() if key not in {"uuid"}])
        conn.execute(
            f"INSERT INTO photos_assets ({columns}) VALUES ({placeholders}) "
            f"ON CONFLICT(uuid) DO UPDATE SET {update_clause}",
            payload,
        )
        added += 1
    conn.commit()
    return added, missing


def _to_int(value):
    try:
        return int(value) if value not in (None, "", "None") else None
    except ValueError:
        return None


def _to_float(value):
    try:
        return float(value) if value not in (None, "", "None") else None
    except ValueError:
        return None


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=args.log_level.upper(), format="%(levelname)s | %(message)s")
    cfg = config_mod.load_config(args.db)
    conn = db_mod.connect(cfg.db_path)
    added, missing = upsert_metadata(conn, args.csv, args.source)
    logger.info("Imported %s rows, %s paths missing from files table", added, missing)


if __name__ == "__main__":  # pragma: no cover
    main()
