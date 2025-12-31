"""Batch OCR for bucket fronts/backs."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import typer
from tqdm import tqdm

from archive_lib import config as config_mod, db as db_mod, log as log_mod
from archive_lib.reporting import load_bucket_infos
from archive_lib.ocr import perform_ocr, vision_available, timestamp

app = typer.Typer(add_completion=False)


@app.command()
def batch(
    source: Optional[str] = typer.Option(None, "--source", help="Limit to this source label"),
    bucket_prefix: Optional[List[str]] = typer.Option(
        None, "--bucket-prefix", help="Only process specific bucket prefixes", rich_help_panel="Filtering"
    ),
    limit: Optional[int] = typer.Option(None, "--limit", help="Max buckets to OCR"),
    include_front: bool = typer.Option(True, "--include-front/--skip-front"),
    include_back: bool = typer.Option(True, "--include-back/--skip-back"),
    force: bool = typer.Option(False, "--force", help="Re-run OCR even if text already exists"),
    resume_prefix: Optional[str] = typer.Option(
        None,
        "--resume-prefix",
        help="Skip all buckets that sort before this bucket prefix (e.g., 3593bcc3…)",
    ),
    progress_file: Optional[Path] = typer.Option(
        None,
        "--progress-file",
        help="Override path for resume checkpoint file",
    ),
    auto_resume: bool = typer.Option(
        True,
        "--auto-resume/--no-auto-resume",
        help="Automatically resume from the last unfinished bucket using a checkpoint file",
    ),
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    """Run Apple Vision OCR across bucket fronts/backs and store machine text in sidecars."""

    if not vision_available():  # pragma: no cover
        typer.echo("Apple Vision OCR unavailable. Install pyobjc-core and pyobjc-framework-Vision.", err=True)
        raise typer.Exit(code=1)

    log_mod.setup_logging(log_level)
    logger = logging.getLogger("cli.ocr")
    cfg = config_mod.load_config()
    conn = db_mod.connect(cfg.db_path)
    infos = load_bucket_infos(conn, cfg, source=source)
    infos = sorted(infos, key=lambda item: (item.source, item.bucket_prefix))
    if bucket_prefix:
        targets = set(bucket_prefix)
        infos = [info for info in infos if info.bucket_prefix in targets]
    progress_path = _resolve_progress_path(cfg, progress_file, auto_resume)
    resume_key = _resume_key(source, bucket_prefix, include_front, include_back)
    resume_hint = resume_prefix or _load_resume_checkpoint(progress_path, resume_key)
    if resume_hint:
        infos = _trim_infos(infos, resume_hint)
        if not infos:
            typer.echo(f"No buckets found at or after resume prefix {resume_hint}", err=True)
            raise typer.Exit(code=1)
        if resume_prefix:
            typer.echo(f"Resuming at bucket prefix {infos[0].bucket_prefix} (requested {resume_hint})")
        elif progress_path:
            typer.echo(
                f"Auto-resuming at bucket prefix {infos[0].bucket_prefix} "
                f"(checkpoint in {progress_path})"
            )
    if limit:
        infos = infos[:limit]
    if not infos:
        typer.echo("No buckets available with the requested filters.", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Running OCR for {len(infos)} buckets (front={include_front}, back={include_back})")
    processed = 0
    skipped = 0
    error_count = 0
    progress = tqdm(infos, unit="bucket")
    completed = False
    try:
        for info in progress:
            progress.set_description(f"bkt_{info.bucket_prefix}")
            try:
                updated = _ocr_bucket(
                    cfg.buckets_dir / f"bkt_{info.bucket_prefix}", info.variants, include_front, include_back, force, logger
                )
            except Exception as exc:  # pragma: no cover
                error_count += 1
                logger.warning("OCR failed for %s: %s", info.bucket_prefix, exc)
                continue
            if updated:
                processed += 1
            else:
                skipped += 1
            _write_resume_checkpoint(progress_path, resume_key, info.bucket_prefix)
        completed = True
    finally:
        if completed:
            _clear_resume_checkpoint(progress_path, resume_key)
    typer.echo(f"OCR complete. updated={processed} skipped={skipped} errors={error_count}")


def _ocr_bucket(
    bucket_dir: Path,
    variants,
    include_front: bool,
    include_back: bool,
    force: bool,
    logger: logging.Logger,
) -> bool:
    sidecar_path = bucket_dir / "sidecar.json"
    if not sidecar_path.exists():
        logger.debug("Missing sidecar for %s", bucket_dir.name)
        return False
    try:
        sidecar = json.loads(sidecar_path.read_text())
    except json.JSONDecodeError:
        logger.warning("Invalid sidecar json for %s", bucket_dir.name)
        return False
    data = sidecar.setdefault("data", {})
    variant_map = _variant_index(variants or data.get("variants") or [])
    auto_ocr = data.setdefault("auto_ocr", {})
    changed = False

    if include_front:
        front_path = _resolve_variant_path(variant_map, ("raw_front", "proxy_front"))
        if front_path and (force or not auto_ocr.get("front_text")):
            auto_ocr["front_text"] = perform_ocr(front_path)
            changed = True
    if include_back:
        back_path = _resolve_variant_path(variant_map, ("raw_back", "proxy_back"))
        if back_path and (force or not auto_ocr.get("back_text")):
            auto_ocr["back_text"] = perform_ocr(back_path)
            changed = True

    if not changed:
        return False

    auto_ocr["engine"] = "apple_vision"
    auto_ocr["updated_at"] = timestamp()
    if not data.get("ocr_status") or force:
        data["ocr_status"] = "machine"
    sidecar_path.write_text(json.dumps(sidecar, ensure_ascii=False, indent=2))
    return True


def _trim_infos(infos, resume_prefix: str):
    trimmed = []
    started = False
    for info in infos:
        if not started and info.bucket_prefix >= resume_prefix:
            started = True
        if started:
            trimmed.append(info)
    return trimmed


def _resolve_progress_path(cfg, progress_file: Optional[Path], auto_resume: bool) -> Optional[Path]:
    if progress_file:
        return progress_file
    if not auto_resume:
        return None
    return cfg.config_dir / "ocr_progress.json"


def _resume_key(
    source: Optional[str],
    bucket_prefix: Optional[List[str]],
    include_front: bool,
    include_back: bool,
) -> str:
    source_label = source or "__all__"
    bucket_label = ",".join(sorted(bucket_prefix or [])) if bucket_prefix else "__all__"
    return f"src={source_label}|buckets={bucket_label}|front={int(include_front)}|back={int(include_back)}"


def _load_resume_checkpoint(progress_file: Optional[Path], resume_key: str) -> Optional[str]:
    if not progress_file or not progress_file.exists():
        return None
    try:
        raw = json.loads(progress_file.read_text())
    except Exception:
        return None
    if isinstance(raw, dict):
        entry = raw.get(resume_key)
        if isinstance(entry, dict):
            prefix = entry.get("last_prefix")
            if isinstance(prefix, str) and prefix:
                return prefix
    elif isinstance(raw, str):
        return raw
    return None


def _write_resume_checkpoint(progress_file: Optional[Path], resume_key: str, bucket_prefix: str) -> None:
    if not progress_file:
        return
    try:
        progress_file.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if progress_file.exists():
            try:
                maybe = json.loads(progress_file.read_text())
                if isinstance(maybe, dict):
                    data = maybe
            except Exception:
                data = {}
        data[resume_key] = {"last_prefix": bucket_prefix, "updated_at": timestamp()}
        progress_file.write_text(json.dumps(data, indent=2))
    except OSError:
        pass


def _clear_resume_checkpoint(progress_file: Optional[Path], resume_key: str) -> None:
    if not progress_file or not progress_file.exists():
        return
    try:
        raw = json.loads(progress_file.read_text())
        if not isinstance(raw, dict):
            progress_file.unlink(missing_ok=True)
            return
        if resume_key in raw:
            raw.pop(resume_key, None)
            if raw:
                progress_file.write_text(json.dumps(raw, indent=2))
            else:
                progress_file.unlink(missing_ok=True)
    except Exception:
        try:
            progress_file.unlink(missing_ok=True)
        except OSError:
            pass


def _variant_index(variants) -> Dict[str, dict]:
    index: Dict[str, dict] = {}
    for variant in variants or []:
        role = getattr(variant, "role", None) or variant.get("role")
        if role and role not in index:
            index[role] = variant
    return index


def _resolve_variant_path(variant_map: Dict[str, dict], roles: Tuple[str, ...]) -> Optional[Path]:
    for role in roles:
        variant = variant_map.get(role)
        if not variant:
            continue
        path_val = variant.get("path") if isinstance(variant, dict) else getattr(variant, "path", None)
        if not path_val:
            continue
        path = Path(str(path_val))
        if path.exists():
            return path
    return None


def run() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    run()
