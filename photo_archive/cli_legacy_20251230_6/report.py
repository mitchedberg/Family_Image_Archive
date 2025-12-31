"""Bucket/reporting CLI with additional diagnostics."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import typer

from archive_lib import config as config_mod, db as db_mod, log as log_mod
from archive_lib.pending import analyze_ai_pending
from archive_lib.reporting import generate_report

app = typer.Typer(add_completion=False)


@app.callback(invoke_without_command=True)
def summary_callback(
    ctx: typer.Context,
    source: Optional[str] = typer.Option(None, "--source", help="Limit to this source label"),
    db: Optional[Path] = typer.Option(None, "--db", help="Path to archive.sqlite"),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging level"),
) -> None:
    """Default report summary when CLI invoked without a subcommand."""
    if ctx.invoked_subcommand is not None:
        return
    log_mod.setup_logging(log_level)
    logger = logging.getLogger("cli.report")
    cfg = config_mod.load_config(db)
    conn = db_mod.connect(cfg.db_path)
    summary = generate_report(conn, cfg, source=source, logger=logger)
    _print_summary(summary)


@app.command("ai_pending")
def ai_pending_command(
    source: str = typer.Option(..., "--source", help="Source label to inspect"),
    db: Optional[Path] = typer.Option(None, "--db", help="Path to archive.sqlite"),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging level"),
    phash: bool = typer.Option(False, "--phash", help="Include perceptual hash suggestions"),
) -> None:
    """Produce reports to resolve AI pending variants."""
    log_mod.setup_logging(log_level)
    logger = logging.getLogger("cli.report.ai_pending")
    cfg = config_mod.load_config(db)
    conn = db_mod.connect(cfg.db_path)
    analyze_ai_pending(conn, cfg, source=source, enable_phash=phash, logger=logger)
    typer.echo(f"Wrote AI pending reports to {cfg.reports_dir}")


def _print_summary(summary) -> None:
    typer.echo("=== Bucket Report ===")
    typer.echo(f"Total buckets: {summary.total_buckets}")
    for role, count in sorted(summary.role_presence.items()):
        percent = (count / summary.total_buckets * 100) if summary.total_buckets else 0
        typer.echo(f"  {role}: {count} ({percent:.1f}%)")
    typer.echo(f"Needs review: {summary.needs_review_count}")
    typer.echo(f"AI-only buckets: {summary.ai_only_count}")
    typer.echo(f"Missing canonical front: {summary.missing_canonical_count}")
    typer.echo(f"Multi-front buckets: {summary.multi_front_count}")
    typer.echo(f"No join key: {summary.no_join_key_count}")
    typer.echo(f"AI orphans: {summary.ai_orphans_count}")
    typer.echo(f"Unassigned files: {summary.unassigned_count}")
    if summary.top_group_keys:
        typer.echo("Top group keys (by total variants):")
        for group_key, total in summary.top_group_keys:
            typer.echo(f"  {group_key or '<blank>'}: {total}")


def run() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    run()
