"""CLI for generating bucket thumbnails."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import typer

from archive_lib import config as config_mod, db as db_mod, log as log_mod
from archive_lib.reporting import load_bucket_infos
from archive_lib.thumbs import Thumbnailer


def main(
    source: Optional[str] = typer.Option(None, "--source", help="Limit to source label"),
    db: Optional[Path] = typer.Option(None, "--db", help="Path to archive.sqlite"),
    force: bool = typer.Option(False, "--force", help="Regenerate even if thumb exists"),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging level"),
) -> None:
    log_mod.setup_logging(log_level)
    logger = logging.getLogger("cli.thumbs")
    cfg = config_mod.load_config(db)
    conn = db_mod.connect(cfg.db_path)
    infos = load_bucket_infos(conn, cfg, source=source)
    thumb = Thumbnailer(cfg, logger=logger, force=force)
    for info in infos:
        thumb.generate(info.bucket_id, list(info.variants))
    logger.info("Generated thumbnails for %d buckets", len(infos))


def run() -> None:  # pragma: no cover
    typer.run(main)


if __name__ == "__main__":  # pragma: no cover
    run()
