"""Filter near-duplicate pairs by removing flagged non-matches."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

import typer

from archive_lib import config as config_mod

app = typer.Typer(add_completion=False)

PHASH_REPORT_DIRNAME = "phash_test"


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
    rejects_file: Path = typer.Option(
        ...,
        "--rejects-file",
        file_okay=True,
        resolve_path=True,
        help="JSON file containing bucket pairs to drop (output of the viewer).",
    ),
    output_name: str = typer.Option(
        "near_duplicates_filtered.csv",
        "--output-name",
        help="Name of the filtered CSV to write into the run folder.",
    ),
) -> None:
    cfg = config_mod.load_config()
    run_dir = _resolve_run_dir(cfg.reports_dir, report_dir, run_id)
    near_csv = run_dir / "near_duplicates.csv"
    if not near_csv.exists():
        raise typer.BadParameter(f"Missing near_duplicates.csv in {run_dir}")
    reject_keys = _load_reject_keys(rejects_file)
    if not reject_keys:
        typer.echo("Rejects file is empty; nothing to remove.")
    filtered_rows, original_count = _filter_csv(near_csv, reject_keys)
    output_csv = run_dir / output_name
    _write_filtered_csv(output_csv, filtered_rows)
    typer.echo(f"Filtered pairs written to {output_csv} (kept {len(filtered_rows)} of {original_count} pairs)")


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


def _iter_csv_rows(path: Path):
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            yield row


def _filter_csv(path: Path, reject_keys: Set[str]) -> Tuple[List[Dict[str, str]], int]:
    rows: List[Dict[str, str]] = []
    original_count = 0
    for row in _iter_csv_rows(path):
        original_count += 1
        a = row.get("bucket_prefix_a", "")
        b = row.get("bucket_prefix_b", "")
        if _pair_key(a, b) in reject_keys:
            continue
        rows.append(row)
    return rows, original_count


def _write_filtered_csv(path: Path, rows: Sequence[Dict[str, str]]) -> None:
    if not rows:
        header = ["bucket_prefix_a", "bucket_prefix_b", "distance", "reason"]
    else:
        header = rows[0].keys()
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


if __name__ == "__main__":  # pragma: no cover
    app()
