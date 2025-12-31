"""CLI for bucket assignment + sidecar generation."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import typer

from archive_lib import config as config_mod, db as db_mod, log as log_mod
from archive_lib.ingest import Assigner


def main(
    source: str = typer.Option(..., "--source", help="Source label (mom|dad|uncle|other)"),
    relpath_prefix: Optional[str] = typer.Option(
        None,
        "--relpath-prefix",
        help="Limit to files whose original_relpath starts with this prefix",
    ),
    preview: Optional[int] = typer.Option(
        None,
        "--preview",
        help="Process only the first N groups (deterministic order)",
        min=1,
    ),
    db: Optional[Path] = typer.Option(None, "--db", help="Path to archive.sqlite"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Do not write bucket dirs or DB rows"),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging level"),
) -> None:
    log_mod.setup_logging(log_level)
    logger = logging.getLogger("cli.assign")
    cfg = config_mod.load_config(db)
    conn = db_mod.connect(cfg.db_path)
    assigner = Assigner(conn, cfg, logger=logger, dry_run=dry_run)
    summary = assigner.run(source=source, relpath_prefix=relpath_prefix, preview=preview)
    logger.info(
        "Processed %d groups | buckets=%d needs_review=%d ai_orphans=%d unassigned=%d",
        summary.groups_processed,
        summary.buckets_created,
        summary.needs_review,
        summary.ai_orphans,
        summary.unassigned,
    )


def run() -> None:  # pragma: no cover
    typer.run(main)


if __name__ == "__main__":  # pragma: no cover
    run()
