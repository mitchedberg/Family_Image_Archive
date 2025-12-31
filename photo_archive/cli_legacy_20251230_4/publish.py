"""Publish preferred bucket variants to Apple Photos staging."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import typer

from archive_lib import config as config_mod, db as db_mod, log as log_mod
from archive_lib.publish import Publisher


def main(
    source: str = typer.Option(..., "--source", help="Source label to publish"),
    prefer_ai: bool = typer.Option(False, "--prefer-ai", help="Prefer AI variants when available"),
    include_ai_only: bool = typer.Option(False, "--include-ai-only", help="Allow AI-only buckets to publish"),
    keywords: bool = typer.Option(False, "--keywords", help="Embed bucket/source keywords via ExifTool"),
    limit: Optional[int] = typer.Option(None, "--limit", help="Limit number of buckets"),
    bucket_prefix: Optional[str] = typer.Option(None, "--bucket-prefix", help="Process only this bucket prefix"),
    prune: bool = typer.Option(False, "--prune", help="Remove published files for buckets that no longer qualify"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show actions without writing output"),
    db: Optional[Path] = typer.Option(None, "--db", help="Path to archive.sqlite"),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging level"),
) -> None:
    log_mod.setup_logging(log_level)
    logger = logging.getLogger("cli.publish")
    cfg = config_mod.load_config(db)
    conn = db_mod.connect(cfg.db_path)
    publisher = Publisher(
        cfg,
        conn,
        logger=logger,
        prefer_ai=prefer_ai,
        include_ai_only=include_ai_only,
        keywords=keywords,
        limit=limit,
        bucket_prefix=bucket_prefix,
        prune=prune,
        dry_run=dry_run,
    )
    publisher.run(source=source)


def run() -> None:  # pragma: no cover
    typer.run(main)


if __name__ == "__main__":  # pragma: no cover
    run()
