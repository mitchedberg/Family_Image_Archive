"""Generate a lightweight HTML viewer for pHash near-duplicate pairs."""
from __future__ import annotations

import csv
import json
import webbrowser
from pathlib import Path
from typing import Dict, List, Optional

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
        help="Path to a specific phash_test/<run_id> directory (defaults to the newest run)",
    ),
    run_id: Optional[str] = typer.Option(
        None,
        "--run-id",
        help="Select reports/phash_test/<run_id> without typing the full path",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        file_okay=True,
        resolve_path=True,
        help="Custom HTML output path (defaults to <report-dir>/viewer.html)",
    ),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Launch the viewer in the default browser"),
) -> None:
    """Build and optionally open a static HTML viewer for near-duplicate pairs."""
    cfg = config_mod.load_config()
    run_dir = _resolve_run_dir(cfg.reports_dir, report_dir, run_id)
    near_csv = run_dir / "near_duplicates.csv"
    fronts_csv = run_dir / "phash_fronts.csv"

    if not near_csv.exists():
        raise typer.BadParameter(f"Missing near_duplicates.csv in {run_dir}")
    if not fronts_csv.exists():
        raise typer.BadParameter(f"Missing phash_fronts.csv in {run_dir}")

    bucket_index = _load_bucket_index(fronts_csv)
    pairs = _load_pairs(near_csv, bucket_index)
    if not pairs:
        typer.echo("No usable pairs found in near_duplicates.csv")
        raise typer.Exit(code=0)

    html_path = output or (run_dir / "viewer.html")
    html_path.parent.mkdir(parents=True, exist_ok=True)
    _write_html(html_path, pairs)
    typer.echo(f"Viewer written to {html_path}")

    if open_browser:
        webbrowser.open(html_path.as_uri())


def _resolve_run_dir(reports_dir: Path, report_dir: Optional[Path], run_id: Optional[str]) -> Path:
    if report_dir:
        return report_dir
    phash_root = reports_dir / PHASH_REPORT_DIRNAME
    if run_id:
        target = phash_root / run_id
        if not target.is_dir():
            raise typer.BadParameter(f"Run id {run_id} not found under {phash_root}")
        return target
    runs = sorted(path for path in phash_root.iterdir() if path.is_dir())
    if not runs:
        raise typer.BadParameter(f"No runs found under {phash_root}")
    return runs[-1]


def _load_bucket_index(fronts_csv: Path) -> Dict[str, dict]:
    index: Dict[str, dict] = {}
    with fronts_csv.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            bucket_prefix = row.get("bucket_prefix")
            if not bucket_prefix:
                continue
            path_value = row.get("image_path") or ""
            image_path = Path(path_value).resolve()
            index[bucket_prefix] = {
                "bucket": bucket_prefix,
                "source": row.get("source", ""),
                "role": row.get("chosen_role") or row.get("role", ""),
                "path": image_path,
                "uri": image_path.as_uri(),
            }
    return index


def _load_pairs(near_csv: Path, index: Dict[str, dict]) -> List[dict]:
    pairs: List[dict] = []
    with near_csv.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            bucket_a = row.get("bucket_prefix_a", "")
            bucket_b = row.get("bucket_prefix_b", "")
            a = index.get(bucket_a)
            b = index.get(bucket_b)
            if not a or not b:
                continue
            pairs.append(
                {
                    "a": a,
                    "b": b,
                    "distance": int(row.get("distance", 0) or 0),
                    "reason": row.get("reason", ""),
                }
            )
    return pairs


def _write_html(output_path: Path, pairs: List[dict]) -> None:
    data_json = json.dumps(pairs, ensure_ascii=False)
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>pHash duplicates viewer</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 0; background: #111; color: #f5f5f5; }}
    header {{ padding: 12px 20px; background: rgba(0,0,0,0.8); position: sticky; top: 0; display: flex; align-items: center; gap: 16px; }}
    header button {{ font-size: 15px; padding: 6px 16px; }}
    #counter {{ font-variant-numeric: tabular-nums; }}
    main {{ display: flex; gap: 12px; padding: 12px; height: calc(100vh - 72px); box-sizing: border-box; }}
    .panel {{ flex: 1; display: flex; flex-direction: column; gap: 8px; }}
    .panel h2 {{ margin: 0; font-size: 18px; }}
    .img-wrap {{ flex: 1; background: #000; border-radius: 6px; padding: 8px; display: flex; justify-content: center; align-items: center; }}
    .img-wrap img {{ max-width: 100%; max-height: 100%; object-fit: contain; }}
    a {{ color: #6bb8ff; }}
    footer {{ position: fixed; bottom: 10px; left: 20px; opacity: 0.7; font-size: 13px; }}
  </style>
</head>
<body>
  <header>
    <button onclick="prevPair()">Prev</button>
    <button onclick="nextPair()">Next</button>
    <div id="counter"></div>
    <div id="meta"></div>
  </header>
  <main>
    <section class="panel">
      <h2 id="labelA"></h2>
      <div class="img-wrap"><img id="imgA" draggable="false" /></div>
      <a id="linkA" target="_blank">Reveal in Finder</a>
    </section>
    <section class="panel">
      <h2 id="labelB"></h2>
      <div class="img-wrap"><img id="imgB" draggable="false" /></div>
      <a id="linkB" target="_blank">Reveal in Finder</a>
    </section>
  </main>
  <footer>Use ← / → keys to step through.</footer>
  <script>
    const pairs = {data_json};
    let index = 0;
    function clamp(i) {{ return Math.min(Math.max(i, 0), pairs.length - 1); }}
    function showPair(i) {{
      index = clamp(i);
      const pair = pairs[index];
      document.getElementById('counter').textContent = `Pair ${index + 1} / ${pairs.length}`;
      document.getElementById('meta').textContent = `distance ${pair.distance} · ${pair.reason || 'phash match'}`;
      const left = pair.a;
      const right = pair.b;
      document.getElementById('labelA').textContent = `${left.bucket} (${left.source || 'unknown'})`;
      document.getElementById('labelB').textContent = `${right.bucket} (${right.source || 'unknown'})`;
      document.getElementById('imgA').src = left.uri;
      document.getElementById('imgB').src = right.uri;
      document.getElementById('linkA').href = left.uri;
      document.getElementById('linkB').href = right.uri;
    }}
    function nextPair() {{ showPair(index + 1); }}
    function prevPair() {{ showPair(index - 1); }}
    document.addEventListener('keydown', (event) => {{
      if (event.key === 'ArrowRight') nextPair();
      if (event.key === 'ArrowLeft') prevPair();
    }});
    showPair(0);
  </script>
</body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")


if __name__ == "__main__":  # pragma: no cover
    app()
