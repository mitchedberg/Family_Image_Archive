"""Pipeline CLI to run ingestion → assignment → thumbs → gallery → publish."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Tuple

import typer

from archive_lib import config as config_mod, db as db_mod, log as log_mod
from archive_lib.pipeline import PipelineRunner, RootSpec, DEFAULT_STEPS, VALID_STEPS
from archive_lib.reporting import load_bucket_infos

app = typer.Typer(help="Run multi-step pipeline for a source.")


def _validate_steps(steps_option: Optional[str]) -> List[str]:
    if not steps_option:
        return DEFAULT_STEPS
    steps = [step.strip().lower() for step in steps_option.split(",") if step.strip()]
    invalid = [step for step in steps if step not in VALID_STEPS]
    if invalid:
        raise typer.BadParameter(f"Unknown steps: {', '.join(invalid)}")
    return steps


def _resolve_roots(paths: List[Path], labels: Optional[List[str]]) -> List[RootSpec]:
    if not paths:
        return []
    resolved = [Path(p).expanduser().resolve() for p in paths]
    if labels and len(labels) != len(resolved):
        raise typer.BadParameter("--root-label count must match --root count")
    entries = []
    for idx, root in enumerate(resolved):
        if not root.exists() or not root.is_dir():
            raise typer.BadParameter(f"Root {root} does not exist or is not a directory")
        label = labels[idx] if labels else None
        entries.append(RootSpec(root, label, "manual"))
    return entries


def _relative_label(parent: Path, child: Path) -> str:
    try:
        return str(child.relative_to(parent))
    except ValueError:
        return str(child.name)


def _discover_auto_roots(parents: Optional[List[Path]]) -> List[RootSpec]:
    if not parents:
        return []
    entries: List[RootEntry] = []
    for parent in parents:
        parent = Path(parent).expanduser().resolve()
        if not parent.exists() or not parent.is_dir():
            raise typer.BadParameter(f"--auto-roots target {parent} is not a directory")
        input_root = parent / "Input"
        raw_dirs: List[Path] = []
        proxy_dirs: List[Path] = []
        if input_root.is_dir():
            raw_dirs = sorted(p for p in input_root.iterdir() if p.is_dir())
            proxy_dirs = sorted(p for p in input_root.rglob("auto-corrected") if p.is_dir())
        output_dir = parent / "Output"
        ordered: List[RootSpec] = []
        for raw in raw_dirs:
            ordered.append(RootSpec(raw, _relative_label(parent, raw), "raw"))
        for proxy in proxy_dirs:
            ordered.append(RootSpec(proxy, _relative_label(parent, proxy), "proxy"))
        if output_dir.is_dir():
            ordered.append(RootSpec(output_dir, _relative_label(parent, output_dir), "ai"))
        entries.extend(ordered)
    return entries


def _dedupe_roots(entries: List[RootSpec]) -> List[RootSpec]:
    seen: dict[Path, RootSpec] = {}
    ordered: List[RootSpec] = []
    for entry in entries:
        if entry.path in seen:
            continue
        seen[entry.path] = entry
        ordered.append(entry)
    return ordered


def _echo_roots(roots: List[RootSpec]) -> None:
    if not roots:
        typer.echo("No roots resolved.")
        return
    typer.echo("Resolved roots:")
    for idx, entry in enumerate(roots, start=1):
        typer.echo(
            f"  {idx:02d}. {entry.path} (label={entry.label or 'n/a'}, role={entry.role.upper()})"
        )


def _expand_staged_roots(paths: Optional[List[Path]]) -> List[RootSpec]:
    entries: List[RootSpec] = []
    for base in paths or []:
        resolved = Path(base).expanduser().resolve()
        if not resolved.exists() or not resolved.is_dir():
            raise typer.BadParameter(f"Staged root {resolved} does not exist or is not a directory")
        children = [child for child in resolved.iterdir() if child.is_dir()]
        targets = children or [resolved]
        for target in targets:
            entries.append(RootSpec(target, target.name, "staged"))
    return entries


def _validate_stage_mode(mode: str) -> str:
    normalized = mode.lower()
    if normalized not in {"copy", "hardlink", "rsync"}:
        raise typer.BadParameter("--stage-mode must be copy, hardlink, or rsync")
    return normalized


def _pending_counts(conn, source: str) -> Tuple[int, int]:
    total = conn.execute(
        "SELECT COUNT(*) FROM pending_variants WHERE source = ?",
        (source,),
    ).fetchone()[0]
    claimed = conn.execute(
        """
        SELECT COUNT(*)
        FROM pending_variants pv
        LEFT JOIN bucket_join_keys bj_fast
          ON bj_fast.source = pv.source
         AND bj_fast.key_type = 'fastfoto'
         AND bj_fast.key_value = pv.fastfoto_token
        LEFT JOIN bucket_join_keys bj_group
          ON bj_group.source = pv.source
         AND bj_group.key_type = 'group_key'
         AND bj_group.key_value = pv.join_key
        WHERE pv.source = ?
          AND (
            bj_fast.bucket_id IS NOT NULL OR
            bj_group.bucket_id IS NOT NULL
          )
        """,
        (source,),
    ).fetchone()[0]
    return total, claimed


def _bucket_stats(conn, cfg, source: str) -> Tuple[int, int]:
    infos = load_bucket_infos(conn, cfg, source=source)
    total = len(infos)
    needs_review = sum(1 for info in infos if info.needs_review)
    return total, needs_review


@app.command()
def run(
    source: str = typer.Option(..., "--source", help="Source label (mom|dad|uncle|other)"),
    root: Optional[List[Path]] = typer.Option(
        None,
        "--root",
        help="Root folder(s) to include (can be repeated)",
    ),
    root_label: Optional[List[str]] = typer.Option(
        None,
        "--root-label",
        help="Label to prefix into original_relpath for the matching --root",
    ),
    auto_roots: List[Path] = typer.Option(
        [],
        "--auto-roots",
        help="Parent folder(s) whose Input/Output subfolders should be ingested automatically",
    ),
    print_roots: bool = typer.Option(False, "--print-roots", help="List resolved roots and exit"),
    steps: Optional[str] = typer.Option(None, "--steps", help="Comma list of steps to run"),
    mode: str = typer.Option("reference", "--mode", help="Storage policy", case_sensitive=False),
    plan: bool = typer.Option(False, "--plan", help="Show plan and exit"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Execute steps in dry-run mode when supported"),
    publish: bool = typer.Option(False, "--publish/--no-publish", help="Run publish step"),
    keywords: bool = typer.Option(False, "--keywords/--no-keywords", help="Embed keywords when publishing"),
    limit: Optional[int] = typer.Option(None, "--limit", help="Limit buckets to publish"),
    bucket_prefix: Optional[str] = typer.Option(None, "--bucket-prefix", help="Publish only this bucket prefix"),
    prefer_ai: bool = typer.Option(False, "--prefer-ai/--no-prefer-ai", help="Prefer AI variants"),
    include_ai_only: bool = typer.Option(False, "--include-ai-only/--skip-ai-only", help="Allow AI-only buckets"),
    prune: bool = typer.Option(False, "--prune/--no-prune", help="Remove stale published files"),
    stage_to_ssd: Optional[Path] = typer.Option(
        None,
        "--stage-to-ssd",
        help="Copy donor roots to this SSD path before ingest",
    ),
    stage_mode: str = typer.Option("copy", "--stage-mode", help="Staging mode (copy|hardlink|rsync)"),
    stage_manifest: Optional[Path] = typer.Option(
        None,
        "--stage-manifest",
        help="Stage manifest CSV path (defaults to reports/stage_manifest.csv)",
    ),
    staging_plan: bool = typer.Option(False, "--staging-plan/--no-staging-plan", help="Plan staging copy counts then exit"),
    staging_only: bool = typer.Option(False, "--staging-only/--no-staging-only", help="Stage files then exit before ingest"),
    staged_root: Optional[List[Path]] = typer.Option(
        None,
        "--staged-root",
        help="Use existing staged roots (skips donor drives)",
    ),
    db: Optional[Path] = typer.Option(None, "--db", help="Path to archive.sqlite"),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging level"),
) -> None:
    mode_input = mode.lower()
    normalized_mode = mode_input.replace("-", "_")
    if normalized_mode not in {"reference", "copy_variants", "copy_all"}:
        raise typer.BadParameter("--mode must be reference, copy-variants, or copy-all")
    stage_mode_value = _validate_stage_mode(stage_mode)
    if stage_to_ssd and staged_root:
        raise typer.BadParameter("Use either --stage-to-ssd or --staged-root, not both")
    if (staging_plan or staging_only) and not stage_to_ssd:
        raise typer.BadParameter("--staging-plan/--staging-only require --stage-to-ssd")
    selected_steps = _validate_steps(steps)
    manual_roots = _resolve_roots(root or [], root_label)
    auto_entries = _discover_auto_roots(auto_roots or None)
    roots = _dedupe_roots(manual_roots + auto_entries)
    staged_root_specs = _expand_staged_roots(staged_root)
    if not roots and not staged_root_specs:
        raise typer.BadParameter("Provide at least one --root/--auto-roots or --staged-root directory.")
    if stage_to_ssd and not roots:
        raise typer.BadParameter("--stage-to-ssd requires donor roots to copy from.")
    log_mod.setup_logging(log_level)
    logger = logging.getLogger("cli.pipeline")
    cfg = config_mod.load_config(db)
    conn = db_mod.connect(cfg.db_path)
    stage_manifest_path = (
        Path(stage_manifest).expanduser().resolve()
        if stage_manifest
        else cfg.reports_dir / "stage_manifest.csv"
    )
    stage_target = Path(stage_to_ssd).expanduser().resolve() if stage_to_ssd else None
    if print_roots:
        _echo_roots(roots)
        raise typer.Exit(code=0)
    publish_options = {
        "keywords": keywords,
        "limit": limit,
        "bucket_prefix": bucket_prefix,
        "prefer_ai": prefer_ai,
        "include_ai_only": include_ai_only,
        "prune": prune,
    }
    runner = PipelineRunner(
        cfg=cfg,
        conn=conn,
        source=source,
        roots=roots,
        mode=normalized_mode,
        steps=selected_steps,
        publish_enabled=publish,
        publish_options=publish_options,
        plan_only=plan,
        dry_run=dry_run,
        logger=logger,
        stage_to_ssd=stage_target,
        stage_mode=stage_mode_value,
        stage_manifest_path=stage_manifest_path,
        staging_plan=staging_plan,
        staging_only=staging_only,
        staged_roots=staged_root_specs,
    )
    if plan:
        _echo_roots(roots)
        typer.echo(runner.plan_description())
        raise typer.Exit(code=0)
    summary = runner.run()
    typer.echo("Pipeline completed:")
    if summary.get("ingest"):
        ingest = summary["ingest"]
        typer.echo(f"  Ingest: {ingest['new']} new / {ingest['total']} total")
    if summary.get("assign"):
        assign = summary["assign"]
        typer.echo(f"  Assign: buckets={assign['buckets_created']} needs_review={assign['needs_review']}")
    if summary.get("variant_copy"):
        vc = summary["variant_copy"]
        typer.echo(f"  Variant copies: {vc['copied']} copied, {vc['missing']} missing")
    if summary.get("thumbs"):
        typer.echo(f"  Thumbs: processed {summary['thumbs']['buckets']} buckets")
    if summary.get("publish"):
        pub = summary["publish"]
        typer.echo(f"  Publish: {pub['published']} outputs (skipped={pub['skipped']})")
    summary_path = cfg.reports_dir / "pipeline_last_run.json"
    typer.echo(f"Summary written to {summary_path}")


@app.command()
def converge(
    source: str = typer.Option(..., "--source", help="Source label (mom|dad|uncle|other)"),
    auto_roots: Optional[List[Path]] = typer.Option(
        None,
        "--auto-roots",
        help="Parent folder(s) to expand",
    ),
    root: Optional[List[Path]] = typer.Option(
        None,
        "--root",
        help="Additional manual root folder(s)",
    ),
    root_label: Optional[List[str]] = typer.Option(
        None,
        "--root-label",
        help="Labels for additional manual roots",
    ),
    stage_to_ssd: Optional[Path] = typer.Option(
        None,
        "--stage-to-ssd",
        help="Copy donor roots to SSD before ingest",
    ),
    stage_mode: str = typer.Option("copy", "--stage-mode", help="Staging mode (copy|hardlink|rsync)"),
    stage_manifest: Optional[Path] = typer.Option(
        None,
        "--stage-manifest",
        help="Stage manifest CSV path (defaults to reports/stage_manifest.csv)",
    ),
    staging_plan: bool = typer.Option(False, "--staging-plan/--no-staging-plan", help="Plan staging copy counts then exit"),
    staging_only: bool = typer.Option(False, "--staging-only/--no-staging-only", help="Stage files then exit before ingest"),
    staged_root: Optional[List[Path]] = typer.Option(
        None,
        "--staged-root",
        help="Use existing staged roots (skips donor drives)",
    ),
    steps: Optional[str] = typer.Option(None, "--steps", help="Comma list overriding converge steps"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Execute converge in dry-run mode"),
    plan: bool = typer.Option(False, "--plan", help="Show plan and exit"),
    db: Optional[Path] = typer.Option(None, "--db", help="Path to archive.sqlite"),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging level"),
) -> None:
    stage_mode_value = _validate_stage_mode(stage_mode)
    if stage_to_ssd and staged_root:
        raise typer.BadParameter("Use either --stage-to-ssd or --staged-root, not both")
    if (staging_plan or staging_only) and not stage_to_ssd:
        raise typer.BadParameter("--staging-plan/--staging-only require --stage-to-ssd")
    log_mod.setup_logging(log_level)
    logger = logging.getLogger("cli.pipeline.converge")
    cfg = config_mod.load_config(db)
    conn = db_mod.connect(cfg.db_path)
    manual_roots = _resolve_roots(root or [], root_label)
    auto_entries = _discover_auto_roots(auto_roots or None)
    roots = _dedupe_roots(manual_roots + auto_entries)
    staged_root_specs = _expand_staged_roots(staged_root)
    if not roots and not staged_root_specs:
        raise typer.BadParameter("Converge requires donor roots or staged roots.")
    if stage_to_ssd and not roots:
        raise typer.BadParameter("--stage-to-ssd requires donor roots to copy from.")
    stage_manifest_path = (
        Path(stage_manifest).expanduser().resolve()
        if stage_manifest
        else cfg.reports_dir / "stage_manifest.csv"
    )
    stage_target = Path(stage_to_ssd).expanduser().resolve() if stage_to_ssd else None
    steps = _validate_steps(steps) if steps else ["init_db", "repair_ai_only", "ingest", "assign", "thumbs", "gallery"]
    runner = PipelineRunner(
        cfg=cfg,
        conn=conn,
        source=source,
        roots=roots,
        mode="reference",
        steps=steps,
        publish_enabled=False,
        publish_options={},
        plan_only=plan,
        dry_run=dry_run,
        logger=logger,
        stage_to_ssd=stage_target,
        stage_mode=stage_mode_value,
        stage_manifest_path=stage_manifest_path,
        staging_plan=staging_plan,
        staging_only=staging_only,
        staged_roots=staged_root_specs,
    )
    if plan:
        _echo_roots(roots)
        typer.echo(runner.plan_description())
        raise typer.Exit(code=0)
    summary = runner.run()
    buckets_total, needs_review = _bucket_stats(conn, cfg, source)
    pending_total, pending_claimed = _pending_counts(conn, source)
    typer.echo("Converge summary:")
    typer.echo(f"  buckets_total={buckets_total}")
    typer.echo(f"  needs_review_count={needs_review}")
    typer.echo(f"  pending_variants_count={pending_total}")
    typer.echo(f"  pending_with_claimed_keys_count={pending_claimed}")
    typer.echo(f"  steps_executed={', '.join(summary.get('steps', []))}")


def main() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
