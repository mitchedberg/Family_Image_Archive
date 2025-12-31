"""CLI entry point for ingest scanner v0."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional

import typer

from archive_lib import config as config_mod, log as log_mod
from archive_lib import db as db_mod
from archive_lib.ingest import Scanner


def main(
    root: List[Path] = typer.Option(..., "--root", help="Root folder(s) to scan"),
    root_label: Optional[List[str]] = typer.Option(
        None,
        "--root-label",
        help="Label for the matching --root path; stored as prefix in original_relpath",
    ),
    source: str = typer.Option(..., "--source", help="Provenance tag (mom|dad|uncle|other)"),
    db: Optional[Path] = typer.Option(None, "--db", help="Path to archive.sqlite"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Collect metadata without writing to DB"),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging level"),
) -> None:
    if not root:
        raise typer.BadParameter("Provide at least one --root path")
    log_mod.setup_logging(log_level)
    logger = logging.getLogger("cli.ingest")
    cfg = config_mod.load_config(db)
    logger.info("Using DB %s", cfg.db_path)
    conn = db_mod.connect(cfg.db_path)
    scanner = Scanner(
        conn,
        source=source,
        dry_run=dry_run,
        reports_dir=cfg.reports_dir,
        logger=logger,
    )
    resolved_roots = [_validate_root(path) for path in root]
    label_map = _build_label_map(resolved_roots, root_label)
    scanner.scan_roots(resolved_roots, root_labels=label_map)
    logger.info("Scan complete")


def _validate_root(path: Path) -> Path:
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists() or not resolved.is_dir():
        raise typer.BadParameter(f"Root {path} does not exist or is not a directory")
    return resolved


def _build_label_map(roots: List[Path], labels: Optional[List[str]]) -> Dict[Path, Optional[str]]:
    if not labels:
        return {root: None for root in roots}
    if len(labels) != len(roots):
        raise typer.BadParameter("--root-label count must match --root count")
    return {root: label or None for root, label in zip(roots, labels)}


def run() -> None:  # pragma: no cover - console entry point
    typer.run(main)


if __name__ == "__main__":  # pragma: no cover
    run()
