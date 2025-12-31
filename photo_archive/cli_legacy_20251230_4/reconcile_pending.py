"""Apply overrides or reconciliation steps for pending variants."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import typer

from archive_lib import config as config_mod, db as db_mod, log as log_mod
from archive_lib.pending import apply_ai_overrides, load_ai_overrides

app = typer.Typer(add_completion=False)


@app.command()
def main(
    source: str = typer.Option(..., "--source", help="Source label to reconcile"),
    apply_ai_overrides_flag: bool = typer.Option(
        False,
        "--apply-ai-overrides",
        help="Attach AI pending rows using ai_overrides.csv",
    ),
    db: Optional[Path] = typer.Option(None, "--db", help="Path to archive.sqlite"),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging level"),
) -> None:
    if not apply_ai_overrides_flag:
        typer.echo("No reconcile action specified. Pass --apply-ai-overrides.", err=True)
        raise typer.Exit(code=1)
    log_mod.setup_logging(log_level)
    logger = logging.getLogger("cli.reconcile_pending")
    cfg = config_mod.load_config(db)
    conn = db_mod.connect(cfg.db_path)
    overrides_path = cfg.config_dir / "ai_overrides.csv"
    overrides = load_ai_overrides(overrides_path)
    if not overrides:
        typer.echo(f"No overrides found at {overrides_path}", err=True)
        raise typer.Exit(code=1)
    summary = apply_ai_overrides(conn, cfg, source=source, overrides=overrides, logger=logger)
    typer.echo(f"Overrides applied: {summary.applied}, skipped: {summary.skipped}")
    typer.echo(f"Details written to {summary.results_path}")


def run() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    run()
