"""SQLite helpers for archive tooling."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable, Sequence


PRAGMAS: Sequence[tuple[str, str]] = (
    ("foreign_keys", "ON"),
    ("journal_mode", "WAL"),
    ("synchronous", "NORMAL"),
)


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _apply_pragmas(conn)
    return conn


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()
    for name, value in PRAGMAS:
        cursor.execute(f"PRAGMA {name} = {value};")
    cursor.close()


def execute_script(conn: sqlite3.Connection, statements: Iterable[str]) -> None:
    cursor = conn.cursor()
    try:
        for statement in statements:
            cursor.execute(statement)
    finally:
        cursor.close()
    conn.commit()
