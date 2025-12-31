"""Maintenance CLI commands for repairing archive state."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import typer

from archive_lib import config as config_mod, db as db_mod, log as log_mod
from archive_lib.repair import RepairSummary, move_ai_only_to_pending

app = typer.Typer(help="Maintenance utilities for repairing archive state.")


@app.command("ai-only-to-pending")
def ai_only_to_pending(
    source: str = typer.Option(..., "--source", help="Source label to repair"),
    db: Optional[Path] = typer.Option(None, "--db", help="Path to archive.sqlite"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report actions without changing anything"),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging level"),
) -> None:
    """Move existing AI-only buckets into pending_variants so they can be reattached later."""
    log_mod.setup_logging(log_level)
    logger = logging.getLogger("cli.repair")
    cfg = config_mod.load_config(db)
    conn = db_mod.connect(cfg.db_path)
    summary: RepairSummary = move_ai_only_to_pending(
        conn,
        cfg,
        source=source,
        logger=logger,
        dry_run=dry_run,
    )
    if summary.buckets_considered == 0:
        typer.echo("No AI-only buckets detected.")
        raise typer.Exit(code=0)
    typer.echo(f"Buckets considered: {summary.buckets_considered}")
    typer.echo(f"Buckets removed: {summary.buckets_removed}")
    typer.echo(f"Variants moved to pending: {summary.variants_moved}")


def main() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
