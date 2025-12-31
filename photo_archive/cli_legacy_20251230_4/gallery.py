"""CLI to build static HTML QC gallery."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import typer

from archive_lib import config as config_mod, db as db_mod, log as log_mod
from archive_lib.gallery import build_gallery


def main(
    source: Optional[str] = typer.Option(None, "--source", help="Limit to source label"),
    db: Optional[Path] = typer.Option(None, "--db", help="Path to archive.sqlite"),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging level"),
) -> None:
    log_mod.setup_logging(log_level)
    logger = logging.getLogger("cli.gallery")
    cfg = config_mod.load_config(db)
    conn = db_mod.connect(cfg.db_path)
    build_gallery(cfg, conn, source=source, logger=logger)


def run() -> None:  # pragma: no cover
    typer.run(main)


if __name__ == "__main__":  # pragma: no cover
    run()
