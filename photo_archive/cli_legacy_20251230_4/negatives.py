"""CLI helpers for forward-only negatives identity workflow."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import typer

from archive_lib import config as config_mod, db as db_mod, log as log_mod
from archive_lib.negatives import (
    NegativePaths,
    default_run_id,
    plan_ai_job as plan_ai_job_impl,
    rename_outputs as rename_outputs_impl,
    repair_proxy_clones,
    resolve_paths,
    export_inputs as export_inputs_impl,
)

app = typer.Typer(help="Negatives-specific workflow commands.")


def _resolve_paths_or_fail(
    *,
    staged_root: Optional[Path],
    cut_root: Optional[Path],
    input_root: Optional[Path],
    output_root: Optional[Path],
    reports_dir: Optional[Path],
) -> NegativePaths:
    try:
        return resolve_paths(
            staged_root=staged_root,
            cut_root=cut_root,
            input_root=input_root,
            output_root=output_root,
            reports_dir=reports_dir,
        )
    except ValueError as exc:  # pragma: no cover - CLI level
        raise typer.BadParameter(str(exc))


@app.command("export_inputs")
def export_inputs(
    source: str = typer.Option("negatives", "--source", help="Source label (default: negatives)"),
    staged_root: Optional[Path] = typer.Option(
        None,
        "--staged-root",
        help="Base staged root that contains Negatives Cut/Input/Output",
    ),
    cut_root: Optional[Path] = typer.Option(None, "--cut-root", help="Override Negatives Cut path"),
    input_root: Optional[Path] = typer.Option(None, "--input-root", help="Override Negatives_Input path"),
    output_root: Optional[Path] = typer.Option(None, "--output-root", help="Override Negatives_Output path"),
    reports_dir: Optional[Path] = typer.Option(None, "--reports-dir", help="Reports directory"),
    run_id: Optional[str] = typer.Option(None, "--run-id", help="Run identifier (auto if omitted)"),
    prefix_len: int = typer.Option(12, "--prefix-len", help="Bucket prefix length"),
    db: Optional[Path] = typer.Option(None, "--db", help="Path to archive.sqlite"),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging level"),
) -> None:
    log_mod.setup_logging(log_level)
    logger = logging.getLogger("cli.negatives.export_inputs")
    cfg = config_mod.load_config(db)
    run = run_id or default_run_id()
    paths = _resolve_paths_or_fail(
        staged_root=staged_root,
        cut_root=cut_root,
        input_root=input_root,
        output_root=output_root,
        reports_dir=reports_dir,
    )
    created, skipped = export_inputs_impl(
        cfg,
        paths,
        source=source,
        run_id=run,
        prefix_len=prefix_len,
        logger=logger,
    )
    typer.echo(f"Export inputs complete | run_id={run} created={created} skipped={skipped}")


@app.command("plan_ai_job")
def plan_ai_job(
    source: str = typer.Option("negatives", "--source", help="Source label"),
    staged_root: Optional[Path] = typer.Option(None, "--staged-root", help="Base staged root"),
    cut_root: Optional[Path] = typer.Option(None, "--cut-root"),
    input_root: Optional[Path] = typer.Option(None, "--input-root"),
    output_root: Optional[Path] = typer.Option(None, "--output-root"),
    reports_dir: Optional[Path] = typer.Option(None, "--reports-dir"),
    input_run_id: Optional[str] = typer.Option(
        None,
        "--input-run-id",
        help="Use entries from this cut_to_input run (defaults to latest)",
    ),
    run_id: Optional[str] = typer.Option(
        None,
        "--run-id",
        help="New AI job run ID (auto-generated if omitted)",
    ),
    db: Optional[Path] = typer.Option(None, "--db"),
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    log_mod.setup_logging(log_level)
    logger = logging.getLogger("cli.negatives.plan_ai_job")
    config_mod.load_config(db)  # ensure DB path exists, even if unused
    paths = _resolve_paths_or_fail(
        staged_root=staged_root,
        cut_root=cut_root,
        input_root=input_root,
        output_root=output_root,
        reports_dir=reports_dir,
    )
    resolved_run, count = plan_ai_job_impl(
        paths,
        source=source,
        input_run_id=input_run_id,
        run_id=run_id,
        logger=logger,
    )
    typer.echo(f"AI job manifest updated | run_id={resolved_run} entries_added={count}")


@app.command("rename_outputs")
def rename_outputs(
    source: str = typer.Option("negatives", "--source", help="Source label"),
    staged_root: Optional[Path] = typer.Option(None, "--staged-root", help="Base staged root"),
    cut_root: Optional[Path] = typer.Option(None, "--cut-root"),
    input_root: Optional[Path] = typer.Option(None, "--input-root"),
    output_root: Optional[Path] = typer.Option(None, "--output-root"),
    reports_dir: Optional[Path] = typer.Option(None, "--reports-dir"),
    only_run_id: str = typer.Option(..., "--only-run-id", help="Run ID to rename outputs for"),
    apply: bool = typer.Option(
        False,
        "--apply/--dry-run",
        help="Apply renames (default dry-run)",
    ),
    db: Optional[Path] = typer.Option(None, "--db"),
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    log_mod.setup_logging(log_level)
    logging.getLogger("PIL").setLevel(logging.WARNING)
    logger = logging.getLogger("cli.negatives.rename_outputs")
    config_mod.load_config(db)
    paths = _resolve_paths_or_fail(
        staged_root=staged_root,
        cut_root=cut_root,
        input_root=input_root,
        output_root=output_root,
        reports_dir=reports_dir,
    )
    renamed, unmapped = rename_outputs_impl(
        paths,
        run_id=only_run_id,
        dry_run=not apply,
        logger=logger,
    )
    mode = "APPLY" if apply else "DRY-RUN"
    typer.echo(f"{mode}: renamed={renamed} unmapped={unmapped} run_id={only_run_id}")


@app.command("repair-proxy-clones")
def repair_proxy_clones_cmd(
    source: str = typer.Option("negatives", "--source", help="Source label to repair"),
    db: Optional[Path] = typer.Option(None, "--db", help="Path to archive.sqlite"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report only"),
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    log_mod.setup_logging(log_level)
    logger = logging.getLogger("cli.negatives.repair")
    cfg = config_mod.load_config(db)
    conn = db_mod.connect(cfg.db_path)
    summary = repair_proxy_clones(conn, cfg, source=source, logger=logger, dry_run=dry_run)
    typer.echo(
        f"Proxy clone repair: groups={summary.duplicate_groups} "
        f"buckets_removed={summary.buckets_removed} "
        f"join_keys={summary.join_keys_reassigned} "
        f"dry_run={summary.dry_run}"
    )


def run() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    run()
