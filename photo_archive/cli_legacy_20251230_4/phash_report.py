"""Rebuild near-duplicate reports from cached pHash data."""
from __future__ import annotations

import csv
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

import typer

from archive_lib import config as config_mod

app = typer.Typer(add_completion=False)

PHASH_REPORT_DIRNAME = "phash_test"
BIN_PREFIX_CHARS = 4  # stay consistent with cli.phash_dupes


@dataclass
class HashRecord:
    bucket_prefix: str
    source: str
    role: str
    image_path: Path
    phash_hex: str


@app.command()
def main(
    report_dir: Optional[Path] = typer.Option(
        None,
        "--report-dir",
        file_okay=True,
        resolve_path=True,
        help="Path to reports/phash_test/<run_id> (defaults to newest run)",
    ),
    run_id: Optional[str] = typer.Option(
        None,
        "--run-id",
        help="Pick a reports/phash_test/<run_id> folder by name instead of --report-dir",
    ),
    new_run_id: Optional[str] = typer.Option(
        None,
        "--new-run-id",
        help="Name of the directory where regenerated reports should be written (defaults to <old_run_id>-t<threshold>)",
    ),
    threshold: int = typer.Option(
        7,
        "--threshold",
        min=0,
        max=64,
        help="Hamming distance threshold for considering a pair a duplicate",
    ),
    rejects_file: Optional[Path] = typer.Option(
        None,
        "--rejects-file",
        file_okay=True,
        resolve_path=True,
        help="JSON file listing pairs (from the viewer) to drop while rebuilding.",
    ),
) -> None:
    """Reuse cached phash_fronts.csv to rebuild near_duplicates.csv at a new threshold."""
    cfg = config_mod.load_config()
    prev_run = _resolve_run_dir(cfg.reports_dir, report_dir, run_id)
    fronts_csv = prev_run / "phash_fronts.csv"
    if not fronts_csv.exists():
        raise typer.BadParameter(f"Missing phash_fronts.csv in {prev_run}")

    records = _load_hash_records(fronts_csv)
    typer.echo(f"Loaded {len(records)} hash records from {fronts_csv}")

    duplicates = _find_duplicates(records, threshold)
    typer.echo(f"Found {len(duplicates)} pairs at threshold <= {threshold}")

    reject_keys = _load_reject_keys(rejects_file) if rejects_file else set()
    if reject_keys:
        before = len(duplicates)
        duplicates = [
            pair for pair in duplicates if _pair_key(pair[0].bucket_prefix, pair[1].bucket_prefix) not in reject_keys
        ]
        typer.echo(f"Filtered {before - len(duplicates)} pairs using rejects file; {len(duplicates)} remaining.")

    out_run_id = new_run_id or f"{prev_run.name}-t{threshold}"
    out_root = prev_run.parent / out_run_id
    out_root.mkdir(parents=True, exist_ok=True)

    _write_dupes_csv(out_root / "near_duplicates.csv", duplicates, threshold)
    shutil.copy2(fronts_csv, out_root / "phash_fronts.csv")
    summary = {
        "derived_from": prev_run.name,
        "threshold": threshold,
        "source_records": len(records),
        "pairs": len(duplicates),
        "rejects_applied": len(reject_keys),
    }
    (out_root / "phash_report_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    typer.echo(f"Regenerated duplicates written to {out_root}")


def _resolve_run_dir(reports_dir: Path, report_dir: Optional[Path], run_id: Optional[str]) -> Path:
    if report_dir:
        return report_dir
    root = reports_dir / PHASH_REPORT_DIRNAME
    if run_id:
        candidate = root / run_id
        if not candidate.is_dir():
            raise typer.BadParameter(f"Run id {run_id} not found under {root}")
        return candidate
    runs = sorted(path for path in root.iterdir() if path.is_dir())
    if not runs:
        raise typer.BadParameter(f"No runs available in {root}")
    return runs[-1]


def _load_hash_records(fronts_csv: Path) -> List[HashRecord]:
    records: List[HashRecord] = []
    with fronts_csv.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            image_path = Path(row["image_path"])
            records.append(
                HashRecord(
                    bucket_prefix=row["bucket_prefix"],
                    source=row.get("source", ""),
                    role=row.get("chosen_role", ""),
                    image_path=image_path,
                    phash_hex=row["phash_hex"],
                )
            )
    return records


def _find_duplicates(records: Sequence[HashRecord], threshold: int) -> List[Tuple[HashRecord, HashRecord, int]]:
    results: List[Tuple[HashRecord, HashRecord, int]] = []
    if len(records) <= 2000:
        candidates = [(i, j) for i in range(len(records)) for j in range(i + 1, len(records))]
    else:
        bins: Dict[str, List[int]] = {}
        for idx, rec in enumerate(records):
            key = rec.phash_hex[:BIN_PREFIX_CHARS]
            bins.setdefault(key, []).append(idx)
        candidates = []
        for entries in bins.values():
            if len(entries) < 2:
                continue
            for i in range(len(entries)):
                for j in range(i + 1, len(entries)):
                    candidates.append((entries[i], entries[j]))
    for i, j in candidates:
        rec_a = records[i]
        rec_b = records[j]
        dist = _hamming_distance(rec_a.phash_hex, rec_b.phash_hex)
        if dist <= threshold:
            results.append((rec_a, rec_b, dist))
    return results


def _hamming_distance(hex_a: str, hex_b: str) -> int:
    a = int(hex_a, 16)
    b = int(hex_b, 16)
    return (a ^ b).bit_count()


def _load_reject_keys(path: Path) -> Set[str]:
    try:
        payload = json.loads(path.read_text())
    except OSError as exc:
        raise typer.BadParameter(f"Failed to read rejects file {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"Rejects file {path} is not valid JSON: {exc}") from exc
    keys: Set[str] = set()
    if isinstance(payload, Sequence):
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            a = entry.get("bucket_prefix_a")
            b = entry.get("bucket_prefix_b")
            if isinstance(a, str) and isinstance(b, str):
                keys.add(_pair_key(a, b))
    return keys


def _pair_key(bucket_a: str, bucket_b: str) -> str:
    order = tuple(sorted((bucket_a, bucket_b)))
    return f"{order[0]}__{order[1]}"


def _write_dupes_csv(path: Path, duplicates: Sequence[Tuple[HashRecord, HashRecord, int]], threshold: int) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["bucket_prefix_a", "bucket_prefix_b", "distance", "reason"])
        for rec_a, rec_b, dist in duplicates:
            writer.writerow([rec_a.bucket_prefix, rec_b.bucket_prefix, dist, f"phash<= {threshold} (rebuild)"])


if __name__ == "__main__":  # pragma: no cover
    app()
