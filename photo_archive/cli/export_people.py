"""Export buckets containing selected people into per-person folders."""
from __future__ import annotations

import csv
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
import sqlite3
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

import typer
from PIL import Image

from archive_lib import config as config_mod, db as db_mod, hashing, log as log_mod
from archive_lib.decisions import DecisionStore
from archive_lib.face_tags import FaceTagStore
from archive_lib.publish import JPEG_QUALITY, PUBLISHED_FILENAME_TEMPLATE
from archive_lib.reporting import BucketInfo, load_bucket_infos
from archive_lib.variant_selector import build_variant_index, select_variant as _select_variant_base

VALID_COPY_MODES = {"copy", "hardlink", "symlink"}
VALID_VARIANT_POLICIES = {"hybrid", "original_only", "ai_only"}
AI_ROLE = "ai_front_v1"
PROXY_ROLE = "proxy_front"
RAW_ROLE = "raw_front"
MANIFEST_NAME = "export_manifest.csv"
PRIMARY_SCOPE = "primary"
ORIGINAL_SCOPE = "original"
ORIGINAL_FILENAME_TEMPLATE = "bkt_{prefix}__original{ext}"
DEFAULT_ORIGINAL_SUFFIX = " Originals"

app = typer.Typer(add_completion=False)


@dataclass
class PersonStats:
    matched: int = 0
    exported: int = 0
    skipped: int = 0
    skipped_reasons: Dict[str, int] = field(default_factory=dict)
    original_exported: int = 0
    original_skipped: int = 0
    original_skipped_reasons: Dict[str, int] = field(default_factory=dict)


@dataclass
class BucketPlan:
    info: BucketInfo
    persons: List[str]
    variant: Dict[str, object]
    variant_role: str
    reason: Optional[str] = None


def _load_people(people: Sequence[str], people_file: Optional[Path]) -> List[str]:
    names: List[str] = []
    seen: Set[str] = set()

    def _add(name: str) -> None:
        cleaned = name.strip()
        if not cleaned or cleaned in seen:
            return
        seen.add(cleaned)
        names.append(cleaned)

    for entry in people:
        _add(entry)
    if people_file:
        if not people_file.exists():
            raise typer.BadParameter(f"people file {people_file} does not exist")
        for line in people_file.read_text(encoding="utf-8").splitlines():
            _add(line)
    if not names:
        raise typer.BadParameter("At least one --people value is required")
    return names


def _select_variant(
    info: BucketInfo,
    decisions: Dict[str, object],
    variant_policy: str,
) -> Tuple[Optional[Dict[str, object]], Optional[str], Optional[str]]:
    """Select variant based on policy and user decisions.

    Returns:
        Tuple of (variant_dict, role_string, skip_reason)
    """
    variant_map = build_variant_index(info.variants)
    preferred = info.preferred_variant or ""

    # Handle explicit preferred variant override
    if preferred and preferred in variant_map:
        return variant_map[preferred], preferred, None

    decision = decisions.get(info.bucket_prefix)
    decision_choice = getattr(decision, "choice", "")
    if variant_policy not in VALID_VARIANT_POLICIES:
        raise ValueError(f"Unsupported variant policy {variant_policy}")

    flag_creepy = decision_choice == "flag_creepy"

    # Determine AI preference based on policy and decision
    prefer_ai = variant_policy == "hybrid"
    if decision_choice == "prefer_original":
        prefer_ai = False
    elif decision_choice == "prefer_ai":
        prefer_ai = True

    # Handle ai_only policy
    if variant_policy == "ai_only":
        if flag_creepy:
            return None, None, "flag_creepy"
        variant = _select_variant_base(info.variants, prefer_ai=True, preferred_role=AI_ROLE)
        if variant:
            return variant, AI_ROLE, None
        return None, None, "missing_ai"

    # Handle original_only policy
    if variant_policy == "original_only":
        # Try proxy first, then raw
        for role in (PROXY_ROLE, RAW_ROLE):
            if role in variant_map:
                return variant_map[role], role, None
        return None, None, "missing_original"

    # Handle hybrid policy with creepy flag
    allow_ai = not flag_creepy
    if not allow_ai:
        # Can't use AI, so force original preference
        variant = _select_variant_base(info.variants, prefer_ai=False)
        if variant:
            role = variant.get("role")
            return variant, role, None
        return None, None, "no_variant"

    # Normal hybrid selection with AI preference
    variant = _select_variant_base(info.variants, prefer_ai=prefer_ai)
    if variant:
        role = variant.get("role")
        return variant, role, None

    return None, None, "no_variant"


def _build_original_folder_name(person: str, suffix: str) -> str:
    label = f"{person}{suffix}"
    cleaned = label.strip()
    return cleaned or person


def _build_original_filename(bucket_prefix: str, source_path: Path) -> str:
    ext = source_path.suffix or ""
    if ext and not ext.startswith("."):
        ext = f".{ext}"
    if not ext:
        ext = ".img"
    return ORIGINAL_FILENAME_TEMPLATE.format(prefix=bucket_prefix, ext=ext.lower())


def _manifest_key(person: str, bucket_prefix: str, scope: str = PRIMARY_SCOPE) -> Tuple[str, str, str]:
    return (person, bucket_prefix, scope)


def _with_scope(row: Dict[str, object], scope: str) -> Dict[str, object]:
    payload = dict(row)
    payload.setdefault("variant_scope", scope)
    return payload


def _record_original_skip(persons: Sequence[str], stats_map: Dict[str, PersonStats], reason: str) -> None:
    label = reason or "missing_original"
    for name in persons:
        stats = stats_map[name]
        stats.original_skipped += 1
        stats.original_skipped_reasons[label] = stats.original_skipped_reasons.get(label, 0) + 1


def _ensure_parent(path: Path, *, dry_run: bool) -> None:
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)


def _write_output_image(source: Path, target: Path, *, dry_run: bool) -> None:
    if dry_run:
        return
    if source.suffix.lower() in {".jpg", ".jpeg"}:
        shutil.copy2(source, target)
        return
    with Image.open(source) as img:
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.save(target, format="JPEG", quality=JPEG_QUALITY)


def _replicate_file(src: Path, dest: Path, mode: str, *, dry_run: bool) -> Tuple[str, bool]:
    if dry_run:
        return (mode, True)
    if dest.exists():
        if dest.is_file() or dest.is_symlink():
            dest.unlink()
        else:
            raise RuntimeError(f"Destination {dest} exists and is not a file")
    if mode == "hardlink":
        try:
            os.link(src, dest)
            return (mode, True)
        except OSError:
            shutil.copy2(src, dest)
            return ("copy_fallback", False)
    if mode == "symlink":
        dest.symlink_to(src)
        return (mode, True)
    shutil.copy2(src, dest)
    return (mode, True)


def _write_keywords(path: Path, info: BucketInfo, persons: Iterable[str], *, dry_run: bool) -> bool:
    if dry_run:
        return False
    keywords = [f"bucket:{info.bucket_prefix}", f"source:{info.source}"]
    if info.group_key:
        keywords.append(f"group:{info.group_key}")
    for name in sorted(persons):
        keywords.append(f"person:{name}")
    args = ["exiftool", "-overwrite_original"]
    args.extend(f"-keywords={kw}" for kw in keywords)
    args.append(str(path))
    try:
        subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except FileNotFoundError:
        raise RuntimeError("exiftool not found; install it or rerun without --keywords")


def _load_manifest(path: Path) -> Dict[Tuple[str, str, str], Dict[str, str]]:
    if not path.exists():
        return {}
    data: Dict[Tuple[str, str, str], Dict[str, str]] = {}
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            person = row.get("person_name", "").strip()
            prefix = row.get("bucket_prefix", "").strip()
            scope = (row.get("variant_scope") or PRIMARY_SCOPE).strip() or PRIMARY_SCOPE
            if person and prefix:
                data[(person, prefix, scope)] = row
    return data


def _write_manifest(path: Path, entries: List[Dict[str, object]], *, dry_run: bool) -> None:
    if dry_run:
        return
    fieldnames = [
        "person_name",
        "bucket_prefix",
        "chosen_role",
        "variant_scope",
        "input_path",
        "input_sha256",
        "output_path",
        "output_sha256",
        "keywords_written",
        "updated_at_utc",
        "notes",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in entries:
            writer.writerow(row)


def _export_original_variants(
    bucket_prefix: str,
    persons: Sequence[str],
    variant: Optional[Dict[str, object]],
    role: Optional[str],
    reason: Optional[str],
    *,
    out_root: Path,
    suffix: str,
    copy_mode: str,
    previous_manifest: Dict[Tuple[str, str, str], Dict[str, str]],
    bucket_exports: Dict[str, Path],
    bucket_sha: Dict[str, str],
    manifest_entries: List[Dict[str, object]],
    person_stats: Dict[str, PersonStats],
    dry_run: bool,
    copy_counts: Dict[str, int],
    role_counts: Dict[str, int],
) -> None:
    if not persons:
        return
    if not variant or not role:
        _record_original_skip(persons, person_stats, reason or "missing_original")
        return
    source_path = Path(str(variant.get("path") or ""))
    if not source_path.exists():
        _record_original_skip(persons, person_stats, "missing_file")
        return
    role_counts[role] = role_counts.get(role, 0) + 1
    folder_names = sorted(_build_original_folder_name(name, suffix) for name in persons)
    if not folder_names:
        return
    anchor_person = folder_names[0]
    filename = _build_original_filename(bucket_prefix, source_path)
    canonical_path = bucket_exports.get(bucket_prefix)
    out_sha = bucket_sha.get(bucket_prefix, "")
    input_sha = str(variant.get("sha256") or "")
    if not input_sha and not dry_run:
        input_sha = hashing.sha256_for_file(source_path)
    if dry_run and not input_sha:
        input_sha = "dry-run"

    if canonical_path is None:
        reuse_anchor = False
        prev_anchor = previous_manifest.get(_manifest_key(anchor_person, bucket_prefix, ORIGINAL_SCOPE))
        if (
            prev_anchor
            and prev_anchor.get("chosen_role") == role
            and prev_anchor.get("input_sha256") == input_sha
        ):
            prev_path = Path(prev_anchor.get("output_path", ""))
            if prev_path.exists():
                canonical_path = prev_path
                bucket_exports[bucket_prefix] = canonical_path
                out_sha = prev_anchor.get("output_sha256") or input_sha or ""
                if not out_sha and not dry_run:
                    out_sha = hashing.sha256_for_file(prev_path)
                if not out_sha:
                    out_sha = "dry-run"
                bucket_sha[bucket_prefix] = out_sha
                reuse_anchor = True
        if not reuse_anchor:
            anchor_path = out_root / anchor_person / filename
            _ensure_parent(anchor_path, dry_run=dry_run)
            if not dry_run and anchor_path.exists():
                anchor_path.unlink()
            _replicate_file(source_path, anchor_path, copy_mode, dry_run=dry_run)
            canonical_path = anchor_path
            bucket_exports[bucket_prefix] = canonical_path
            if dry_run:
                out_sha = "dry-run"
            else:
                out_sha = input_sha or hashing.sha256_for_file(canonical_path)
            bucket_sha[bucket_prefix] = out_sha

    if canonical_path is None:
        _record_original_skip(persons, person_stats, "write_failed")
        return

    for name in persons:
        folder_name = _build_original_folder_name(name, suffix)
        dest_path = out_root / folder_name / filename
        prev = previous_manifest.get(_manifest_key(folder_name, bucket_prefix, ORIGINAL_SCOPE))
        if prev and prev.get("output_sha256") == out_sha and Path(prev.get("output_path", "")).exists():
            person_stats[name].original_exported += 1
            manifest_entries.append(_with_scope(prev, ORIGINAL_SCOPE))
            continue
        if folder_name == anchor_person:
            actual_path = canonical_path
        else:
            _ensure_parent(dest_path, dry_run=dry_run)
            mode_used, _ = _replicate_file(canonical_path, dest_path, copy_mode, dry_run=dry_run)
            copy_counts[mode_used] = copy_counts.get(mode_used, 0) + 1
            actual_path = dest_path
        entry = {
            "person_name": folder_name,
            "bucket_prefix": bucket_prefix,
            "chosen_role": role,
            "variant_scope": ORIGINAL_SCOPE,
            "input_path": str(source_path),
            "input_sha256": input_sha,
            "output_path": str(actual_path),
            "output_sha256": "dry-run" if dry_run else (out_sha or input_sha),
            "keywords_written": 0,
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
            "notes": "",
        }
        manifest_entries.append(entry)
        person_stats[name].original_exported += 1

def _connect_db(cfg: config_mod.AppConfig, *, readonly: bool) -> sqlite3.Connection:
    if readonly:
        uri = f"file:{cfg.db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    conn = db_mod.connect(cfg.db_path)
    return conn


@app.command()
def main(
    people: List[str] = typer.Option([], "--people", help="Person name to include (repeatable)"),
    people_file: Optional[Path] = typer.Option(None, "--people-file", help="Optional newline-delimited list of names"),
    out_root: Path = typer.Option(..., "--out-root", help="Destination folder for per-person exports"),
    archive_root: Optional[Path] = typer.Option(None, "--archive-root", help="Validate against detected archive root"),
    source: Optional[List[str]] = typer.Option(None, "--source", help="Limit to these source labels"),
    variant_policy: str = typer.Option("hybrid", "--variant-policy", case_sensitive=False, help="hybrid|original_only|ai_only"),
    copy_mode: str = typer.Option("hardlink", "--copy-mode", case_sensitive=False, help="copy|hardlink|symlink"),
    keywords: bool = typer.Option(False, "--keywords/--no-keywords", help="Write Exif keywords (needs exiftool)"),
    limit: int = typer.Option(0, "--limit", help="Limit total unique buckets (0 = no limit)"),
    dry_run: bool = typer.Option(False, "--dry-run/--apply", help="Preview work without writing files"),
    db_readonly: bool = typer.Option(
        False,
        "--db-readonly/--db-writable",
        help="Open archive.sqlite in read-only mode (recommended for exports)",
    ),
    mirror_originals: bool = typer.Option(
        False,
        "--mirror-originals/--skip-originals",
        help="Also export raw/proxy originals into '<Name> Originals' folders",
    ),
    originals_suffix: str = typer.Option(
        DEFAULT_ORIGINAL_SUFFIX,
        "--originals-suffix",
        help="Suffix appended to person folders for original copies",
    ),
    originals_copy_mode: Optional[str] = typer.Option(
        None,
        "--originals-copy-mode",
        case_sensitive=False,
        help="Optional copy mode for originals (default copy when mirroring)",
    ),
) -> None:
    """Export one preferred image per bucket for the requested people."""

    names = _load_people(people, people_file)
    copy_mode = copy_mode.lower()
    variant_policy = variant_policy.lower()
    if copy_mode not in VALID_COPY_MODES:
        raise typer.BadParameter("--copy-mode must be copy, hardlink, or symlink")
    if variant_policy not in VALID_VARIANT_POLICIES:
        raise typer.BadParameter("--variant-policy must be hybrid, original_only, or ai_only")
    orig_copy_mode = copy_mode
    if mirror_originals:
        orig_copy_mode = originals_copy_mode.lower() if originals_copy_mode else "copy"
        if orig_copy_mode not in VALID_COPY_MODES:
            raise typer.BadParameter("--originals-copy-mode must be copy, hardlink, or symlink")

    log_mod.setup_logging("INFO")
    cfg = config_mod.load_config()
    expected_root = cfg.staging_root
    if archive_root and expected_root != archive_root:
        raise typer.BadParameter(f"--archive-root {archive_root} does not match detected {expected_root}")

    conn = _connect_db(cfg, readonly=db_readonly)
    decisions = DecisionStore(cfg.config_dir / "ai_choices.csv").all()
    infos = load_bucket_infos(conn, cfg)
    if source:
        allowed = set(source)
        infos = [info for info in infos if info.source in allowed]
    bucket_map = {info.bucket_prefix: info for info in infos}

    tag_store = FaceTagStore(cfg.config_dir / "face_tags.csv")
    tags = tag_store.all()

    person_buckets: Dict[str, Set[str]] = {name: set() for name in names}
    for tag in tags.values():
        if tag.label in person_buckets and tag.bucket_prefix in bucket_map:
            person_buckets[tag.label].add(tag.bucket_prefix)

    bucket_people: Dict[str, List[str]] = {}
    person_stats: Dict[str, PersonStats] = {name: PersonStats() for name in names}
    for name in names:
        prefixes = sorted(person_buckets[name])
        for prefix in prefixes:
            person_stats[name].matched += 1
            bucket_people.setdefault(prefix, []).append(name)

    if not bucket_people:
        typer.echo("No buckets matched the requested people.", err=True)
        raise typer.Exit(code=1)

    planned_buckets = sorted(bucket_people.keys())
    if limit and limit > 0:
        planned_buckets = planned_buckets[:limit]

    out_root = out_root.resolve()
    manifest_path = out_root / MANIFEST_NAME
    previous_manifest = _load_manifest(manifest_path)
    manifest_entries: List[Dict[str, object]] = []

    bucket_exports: Dict[str, Path] = {}
    bucket_sha: Dict[str, str] = {}
    bucket_original_exports: Dict[str, Path] = {}
    bucket_original_sha: Dict[str, str] = {}
    role_counts: Dict[str, int] = {}
    original_role_counts: Dict[str, int] = {}
    copy_counts: Dict[str, int] = {}
    keywords_written = 0

    for bucket_prefix in planned_buckets:
        info = bucket_map.get(bucket_prefix)
        persons = bucket_people.get(bucket_prefix, [])
        if not info or not persons:
            continue
        variant, role, reason = _select_variant(info, decisions, variant_policy)
        original_variant = None
        original_role = None
        original_reason = None
        if mirror_originals:
            original_variant, original_role, original_reason = _select_variant(info, decisions, "original_only")
        if not variant or not role:
            for name in persons:
                person_stats[name].skipped += 1
                person_stats[name].skipped_reasons[reason or "unknown"] = (
                    person_stats[name].skipped_reasons.get(reason or "unknown", 0) + 1
                )
            continue
        source_path = Path(str(variant.get("path") or ""))
        if not source_path.exists():
            for name in persons:
                person_stats[name].skipped += 1
                person_stats[name].skipped_reasons["missing_file"] = (
                    person_stats[name].skipped_reasons.get("missing_file", 0) + 1
                )
            continue
        role_counts[role] = role_counts.get(role, 0) + 1
        anchor_person = sorted(persons)[0]
        anchor_path = out_root / anchor_person / PUBLISHED_FILENAME_TEMPLATE.format(prefix=bucket_prefix)
        canonical_path = bucket_exports.get(bucket_prefix)
        input_sha = str(variant.get("sha256") or "")
        if not input_sha and not dry_run:
            input_sha = hashing.sha256_for_file(source_path)
        if dry_run and not input_sha:
            input_sha = "dry-run"
        if canonical_path is None:
            reuse_anchor = False
            prev_anchor = previous_manifest.get(_manifest_key(anchor_person, bucket_prefix, PRIMARY_SCOPE))
            if (
                prev_anchor
                and prev_anchor.get("chosen_role") == role
                and prev_anchor.get("input_sha256") == input_sha
            ):
                prev_path = Path(prev_anchor.get("output_path", ""))
                if prev_path.exists():
                    canonical_path = prev_path
                    bucket_exports[bucket_prefix] = canonical_path
                    out_sha = prev_anchor.get("output_sha256") or ""
                    if not out_sha and not dry_run:
                        out_sha = hashing.sha256_for_file(prev_path)
                    if not out_sha:
                        out_sha = "dry-run"
                    bucket_sha[bucket_prefix] = out_sha
                    reuse_anchor = True
            if not reuse_anchor:
                _ensure_parent(anchor_path, dry_run=dry_run)
                if not dry_run and anchor_path.exists():
                    anchor_path.unlink()
                _write_output_image(source_path, anchor_path, dry_run=dry_run)
                canonical_path = anchor_path
                bucket_exports[bucket_prefix] = canonical_path
                if dry_run:
                    out_sha = "dry-run"
                else:
                    out_sha = hashing.sha256_for_file(canonical_path)
                    if keywords:
                        if _write_keywords(canonical_path, info, persons, dry_run=dry_run):
                            keywords_written += 1
                bucket_sha[bucket_prefix] = out_sha
        if canonical_path is None:
            # Should not happen, but guard against it
            for name in persons:
                person_stats[name].skipped += 1
            continue
        else:
            _ensure_parent(anchor_path, dry_run=dry_run)
            out_sha = bucket_sha[bucket_prefix]

        for name in persons:
            dest_path = out_root / name / PUBLISHED_FILENAME_TEMPLATE.format(prefix=bucket_prefix)
            prev = previous_manifest.get(_manifest_key(name, bucket_prefix, PRIMARY_SCOPE))
            if prev and prev.get("output_sha256") == out_sha and Path(prev.get("output_path", "")).exists():
                person_stats[name].exported += 1
                manifest_entries.append(_with_scope(prev, PRIMARY_SCOPE))
                continue
            if name == anchor_person:
                # already written above
                actual_path = canonical_path
            else:
                _ensure_parent(dest_path, dry_run=dry_run)
                mode_used, _ = _replicate_file(canonical_path, dest_path, copy_mode, dry_run=dry_run)
                copy_counts[mode_used] = copy_counts.get(mode_used, 0) + 1
                actual_path = dest_path
            if dry_run:
                output_sha = "dry-run"
            else:
                output_sha = out_sha
            entry = {
                "person_name": name,
                "bucket_prefix": bucket_prefix,
                "chosen_role": role,
                "variant_scope": PRIMARY_SCOPE,
                "input_path": str(source_path),
                "input_sha256": input_sha,
                "output_path": str(actual_path),
                "output_sha256": output_sha,
                "keywords_written": int(keywords and not dry_run),
                "updated_at_utc": datetime.now(timezone.utc).isoformat(),
                "notes": "",
            }
            manifest_entries.append(entry)
            person_stats[name].exported += 1

        if mirror_originals:
            _export_original_variants(
                bucket_prefix=bucket_prefix,
                persons=persons,
                variant=original_variant,
                role=original_role,
                reason=original_reason,
                out_root=out_root,
                suffix=originals_suffix,
                copy_mode=orig_copy_mode,
                previous_manifest=previous_manifest,
                bucket_exports=bucket_original_exports,
                bucket_sha=bucket_original_sha,
                manifest_entries=manifest_entries,
                person_stats=person_stats,
                dry_run=dry_run,
                copy_counts=copy_counts,
                role_counts=original_role_counts,
            )

    _write_manifest(manifest_path, manifest_entries, dry_run=dry_run)
    conn.close()

    typer.echo("Export complete" if not dry_run else "Dry-run summary")
    typer.echo(f"People: {', '.join(names)}")
    typer.echo(f"Destination: {out_root}")
    for name in names:
        stats = person_stats[name]
        if stats.matched == 0:
            typer.echo(f"- {name}: no matches")
            continue
        reason_bits = ", ".join(f"{k}={v}" for k, v in sorted(stats.skipped_reasons.items()))
        line = f"- {name}: matched {stats.matched}, exported {stats.exported}, skipped {stats.skipped}"
        if reason_bits:
            line += f" ({reason_bits})"
        if mirror_originals:
            original_bits = ", ".join(f"{k}={v}" for k, v in sorted(stats.original_skipped_reasons.items()))
            line += f"; originals exported {stats.original_exported}, originals skipped {stats.original_skipped}"
            if original_bits:
                line += f" ({original_bits})"
        typer.echo(line)
    typer.echo(
        "Variant roles exported: "
        + ", ".join(f"{role}={count}" for role, count in sorted(role_counts.items()))
    )
    if mirror_originals and original_role_counts:
        typer.echo(
            "Original roles exported: "
            + ", ".join(f"{role}={count}" for role, count in sorted(original_role_counts.items()))
        )
    if copy_counts:
        typer.echo(
            "Copy modes used: "
            + ", ".join(f"{mode}={count}" for mode, count in sorted(copy_counts.items()))
        )
    if keywords:
        typer.echo(f"Keyword writes: {keywords_written}")


def run() -> None:  # pragma: no cover - console entry
    typer.run(main)


if __name__ == "__main__":  # pragma: no cover
    run()
