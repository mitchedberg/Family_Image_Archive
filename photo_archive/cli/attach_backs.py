"""Attach back scans to their matching front buckets using Photos metadata."""
from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

import typer

from archive_lib import config as config_mod

app = typer.Typer(add_completion=False)

BACK_SUFFIX = "_b"


@dataclass
class BucketRecord:
    prefix: str
    sidecar_path: Path
    data: Dict[str, object]
    original_filename: str
    is_back: bool
    base_name: str

    @property
    def variants(self) -> List[dict]:  # type: ignore[override]
        existing = self.data.get("variants")
        if isinstance(existing, list):
            return existing
        new_list: List[dict] = []
        self.data["variants"] = new_list
        return new_list


def _load_bucket_records(cfg: config_mod.AppConfig, source: str) -> Tuple[List[BucketRecord], List[BucketRecord]]:
    fronts: List[BucketRecord] = []
    backs: List[BucketRecord] = []
    buckets_dir = cfg.buckets_dir
    for sidecar_path in buckets_dir.glob("bkt_*/sidecar.json"):
        try:
            payload = json.loads(sidecar_path.read_text())
        except json.JSONDecodeError:
            continue
        data = payload.get("data")
        if not isinstance(data, dict):
            continue
        source_label = payload.get("source") or data.get("source")
        if source_label != source:
            continue
        photos = data.get("photos_asset")
        if not isinstance(photos, dict):
            continue
        original_name = str(photos.get("original_filename") or "").strip()
        if not original_name:
            continue
        base_name, is_back = _split_fastfoto_name(original_name)
        prefix = data.get("bucket_prefix") or _derive_prefix(sidecar_path)
        record = BucketRecord(
            prefix=prefix,
            sidecar_path=sidecar_path,
            data=data,
            original_filename=original_name,
            is_back=is_back,
            base_name=base_name,
        )
        if is_back:
            backs.append(record)
        else:
            fronts.append(record)
    return fronts, backs


def _split_fastfoto_name(name: str) -> Tuple[str, bool]:
    stem = name
    ext = ""
    if "." in name:
        stem, ext = name.rsplit(".", 1)
    lower = stem.lower()
    if lower.endswith(BACK_SUFFIX):
        return f"{stem[:-len(BACK_SUFFIX)]}.{ext}" if ext else stem[:-len(BACK_SUFFIX)], True
    return name, False


def _derive_prefix(path: Path) -> str:
    return path.parent.name.replace("bkt_", "")


@app.command()
def main(
    source: str = typer.Option("family_photos", "--source", help="Bucket source label to scan"),
    limit: int = typer.Option(0, "--limit", help="Max attachments to perform (0 = all)"),
    apply: bool = typer.Option(False, "--apply/--dry-run", help="Write changes to disk"),
    verbose: bool = typer.Option(False, "--verbose/--quiet"),
) -> None:
    cfg = config_mod.load_config()
    fronts, backs = _load_bucket_records(cfg, source)
    if not fronts or not backs:
        typer.echo(f"No eligible buckets found for source '{source}'.")
        raise typer.Exit(code=1)

    fronts_by_base: Dict[str, List[BucketRecord]] = {}
    backs_by_base: Dict[str, List[BucketRecord]] = {}
    for rec in fronts:
        fronts_by_base.setdefault(rec.base_name.lower(), []).append(rec)
    for rec in backs:
        backs_by_base.setdefault(rec.base_name.lower(), []).append(rec)

    total_matches = 0
    attached = 0
    skipped_multi = 0
    for base, back_records in backs_by_base.items():
        front_records = fronts_by_base.get(base) or []
        if len(front_records) != 1 or len(back_records) != 1:
            skipped_multi += 1
            if verbose:
                typer.echo(
                    f"Skipping base '{base}': fronts={len(front_records)} backs={len(back_records)}"
                )
            continue
        total_matches += 1
        front = front_records[0]
        back = back_records[0]
        if _front_has_back_variant(front):
            if verbose:
                typer.echo(f"Front bucket {front.prefix} already has a back variant; skipping.")
            continue
        action = f"Attach back ({back.original_filename}) -> front bucket {front.prefix}"
        if not apply:
            typer.echo(f"[DRY-RUN] {action}")
        else:
            _attach_back_variant(front, back)
            typer.echo(f"[APPLY] {action}")
        attached += 1
        if limit and attached >= limit:
            break

    typer.echo(
        f"Matches evaluated: {total_matches}, attached: {attached}, skipped ambiguous: {skipped_multi}, mode={'apply' if apply else 'dry-run'}"
    )


def _front_has_back_variant(front: BucketRecord) -> bool:
    for variant in front.variants:
        if variant.get("role") in {"raw_back", "proxy_back"}:
            return True
    return False


def _attach_back_variant(front: BucketRecord, back: BucketRecord) -> None:
    front_variants = front.variants
    back_variant = _select_back_variant(back)
    if back_variant is None:
        return
    new_variant = deepcopy(back_variant)
    new_variant["role"] = "raw_back"
    new_variant["is_primary"] = False
    notes = new_variant.setdefault("notes", [])
    if isinstance(notes, list):
        notes.append(f"attached_from_bucket:{back.prefix}")
    else:
        new_variant["notes"] = [notes, f"attached_from_bucket:{back.prefix}"]
    front_variants.append(new_variant)

    meta = front.data.setdefault("back_links", [])  # type: ignore[arg-type]
    link_entry = {
        "source_bucket": back.prefix,
        "original_filename": back.original_filename,
        "attached_at": _timestamp(),
    }
    if isinstance(meta, list):
        meta.append(link_entry)
    else:
        front.data["back_links"] = [link_entry]

    back.data.setdefault("attached_to_bucket", front.prefix)
    _write_sidecar(front.sidecar_path, front.data)
    _write_sidecar(back.sidecar_path, back.data)


def _select_back_variant(back: BucketRecord) -> dict | None:
    for role in ("raw_front", "proxy_front"):
        for variant in back.variants:
            if variant.get("role") == role:
                return variant
    if back.variants:
        return back.variants[0]
    return None


def _write_sidecar(path: Path, data: Dict[str, object]) -> None:
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError:
        payload = {"data": data}
    else:
        payload["data"] = data
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    app()
