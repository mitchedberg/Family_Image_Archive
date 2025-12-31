"""CLI helpers for managing derived web/thumbnail assets."""
from __future__ import annotations

import logging
from typing import List, Optional

import typer

from archive_lib import config as config_mod, db as db_mod, log as log_mod
from archive_lib.derived_state import mark_buckets_dirty
from archive_lib.reporting import load_bucket_infos
from archive_lib.webimage import ensure_web_images

app = typer.Typer(help="Manage derived review assets.")


@app.command("refresh")
def refresh(
    source: Optional[str] = typer.Option(None, "--source", help="Limit to this source label"),
    bucket_prefix: Optional[List[str]] = typer.Option(
        None, "--bucket-prefix", help="Only refresh specific bucket prefixes (repeatable)"
    ),
    force: bool = typer.Option(False, "--force", help="Regenerate even if cache looks current"),
    dirty_only: bool = typer.Option(
        True,
        "--dirty-only/--all",
        help="Only refresh buckets whose derived_state indicates stale assets",
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    """Refresh derived images without launching the review UI."""
    log_mod.setup_logging(log_level)
    logger = logging.getLogger("cli.derived.refresh")
    cfg = config_mod.load_config()
    conn = db_mod.connect(cfg.db_path)
    infos = load_bucket_infos(conn, cfg, source=source)
    if bucket_prefix:
        requested = set(bucket_prefix)
        infos = [info for info in infos if info.bucket_prefix in requested]
        if not infos:
            typer.echo("No buckets match the requested prefixes", err=True)
            raise typer.Exit(code=1)
    counts = ensure_web_images(
        infos,
        cfg.buckets_dir,
        logger=logger,
        force=force,
        dirty_only=dirty_only and not force,
        update_state=True,
    )
    typer.echo(
        "Refresh complete: "
        f"created={counts['created']} skipped={counts['skipped']} "
        f"missing={counts['missing_source']} clean={counts['clean']}"
    )


@app.command("mark-dirty")
def mark_dirty(
    source: Optional[str] = typer.Option(None, "--source", help="Limit to this source label"),
    bucket_prefix: Optional[List[str]] = typer.Option(
        None, "--bucket-prefix", help="Mark only specific bucket prefixes (repeatable)"
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    """Force derived refresh the next time refresh/review runs."""
    log_mod.setup_logging(log_level)
    cfg = config_mod.load_config()
    conn = db_mod.connect(cfg.db_path)
    if bucket_prefix:
        prefixes = bucket_prefix
    else:
        cursor = conn.execute(
            "SELECT bucket_prefix FROM buckets" + (" WHERE source = ?" if source else ""),
            (source,) if source else (),
        )
        prefixes = [row["bucket_prefix"] for row in cursor.fetchall()]
        cursor.close()
    if not prefixes:
        typer.echo("No bucket prefixes found to mark dirty", err=True)
        raise typer.Exit(code=1)
    updated = mark_buckets_dirty(cfg.buckets_dir, prefixes=prefixes, reason="manual_mark")
    typer.echo(f"Marked {updated} bucket(s) dirty")


def run() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    run()
