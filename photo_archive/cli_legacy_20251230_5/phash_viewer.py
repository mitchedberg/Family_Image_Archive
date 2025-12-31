"""Interactive reviewer for pHash matches with persistent state, slider filtering, and manual navigation."""
from __future__ import annotations

import csv
import http.server
import json
import mimetypes
import socketserver
import threading
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import typer

from archive_lib import config as config_mod

app = typer.Typer(add_completion=False)

PHASH_REPORT_DIRNAME = "phash_test"
STATE_FILENAME = "phash_review_state.json"


@app.command()
def main(
    report_dir: Optional[Path] = typer.Option(
        None,
        "--report-dir",
        file_okay=True,
        resolve_path=True,
        help="Path to a specific phash_test/<run_id> directory (defaults to newest run)",
    ),
    run_id: Optional[str] = typer.Option(
        None,
        "--run-id",
        help="Select reports/phash_test/<run_id> without typing the full path",
    ),
    rejects_file: Optional[Path] = typer.Option(
        None,
        "--rejects-file",
        file_okay=True,
        resolve_path=True,
        help="Override where rejected pairs are stored",
    ),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Automatically open the viewer"),
) -> None:
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
        typer.echo("No usable pairs found.")
        raise typer.Exit(code=0)

    reject_path = rejects_file or (run_dir / "phash_rejects.json")
    state_path = run_dir.parent / STATE_FILENAME
    context = ViewerContext(pairs=pairs, rejects_path=reject_path, state_path=state_path)
    handler_cls = _make_handler(context)
    server = ThreadedHTTPServer(("127.0.0.1", 0), handler_cls)
    url = f"http://{server.server_address[0]}:{server.server_address[1]}/"
    typer.echo(f"Viewer running at {url}")
    typer.echo(f"State stored in {state_path} (rejects mirrored to {reject_path})")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        typer.echo("Shutting down viewer…")
    finally:
        server.shutdown()
        server.server_close()


class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


class ViewerContext:
    def __init__(self, pairs: List[dict], rejects_path: Path, state_path: Path):
        self.pairs = pairs
        self.rejects_path = rejects_path
        self.state_path = state_path
        self.pair_lookup: Dict[str, tuple[str, str]] = {
            pair["key"]: (pair["a"]["bucket"], pair["b"]["bucket"]) for pair in pairs
        }
        self.lock = threading.Lock()
        self.state = self._load_state()
        self.image_paths: Dict[str, Path] = {}
        for pair in pairs:
            for side in ("a", "b"):
                entry = pair[side]
                bucket = entry["bucket"]
                if bucket not in self.image_paths:
                    self.image_paths[bucket] = Path(entry["path"])
        for pair in pairs:
            pair["status"] = self.state.get(pair["key"], "pending")
        self.original_total = len(pairs)
        self.max_distance = max(pair.get("distance", 0) for pair in pairs)
        self._persist_run_rejects()

    def _load_state(self) -> Dict[str, str]:
        if not self.state_path.exists():
            return {}
        try:
            data = json.loads(self.state_path.read_text())
        except Exception:
            return {}
        if isinstance(data, dict):
            return {str(key): str(value) for key, value in data.items()}
        return {}

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state, indent=2), encoding="utf-8")

    def _persist_run_rejects(self) -> None:
        payload = []
        for key, status in self.state.items():
            if status != "reject":
                continue
            buckets = self.pair_lookup.get(key)
            if not buckets:
                continue
            payload.append({"bucket_prefix_a": buckets[0], "bucket_prefix_b": buckets[1]})
        self.rejects_path.parent.mkdir(parents=True, exist_ok=True)
        self.rejects_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def update_state(self, key: str, status: str) -> bool:
        if key not in self.pair_lookup:
            return False
        with self.lock:
            if status in ("match", "reject"):
                self.state[key] = status
            elif status == "pending":
                self.state.pop(key, None)
            for pair in self.pairs:
                if pair["key"] == key:
                    pair["status"] = status
                    break
            self._save_state()
            self._persist_run_rejects()
        return True

    def render_html(self) -> str:
        data_json = json.dumps(self.pairs, ensure_ascii=False)
        summary = {"original": self.original_total, "max_distance": self.max_distance}
        summary_json = json.dumps(summary)
        html = f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <title>pHash duplicate reviewer</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 0; background: #111; color: #f5f5f5; }}
    header {{ padding: 12px 20px; background: rgba(0,0,0,0.85); position: sticky; top: 0; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
    header button {{ font-size: 14px; padding: 6px 16px; }}
    #counter {{ font-variant-numeric: tabular-nums; }}
    main {{ display: flex; gap: 12px; padding: 12px; height: calc(100vh - 120px); box-sizing: border-box; }}
    .panel {{ flex: 1; display: flex; flex-direction: column; gap: 8px; }}
    .panel h2 {{ margin: 0; font-size: 18px; }}
    .img-wrap {{ flex: 1; background: #000; border-radius: 6px; padding: 8px; display: flex; justify-content: center; align-items: center; }}
    .img-wrap img {{ max-width: 100%; max-height: 100%; object-fit: contain; }}
    a {{ color: #6bb8ff; }}
    footer {{ position: fixed; bottom: 10px; left: 20px; opacity: 0.8; font-size: 13px; }}
    #done {{ padding: 40px; text-align: center; font-size: 20px; }}
    #controls {{ width: 100%; display: flex; align-items: center; gap: 12px; }}
    #distanceSlider {{ width: 180px; }}
  </style>
</head>
<body>
  <header>
    <button onclick=\"prevPair()\">Back (←)</button>
    <button onclick=\"skipPair()\">Next (→)</button>
    <button onclick=\"markMatch()\">Match · Next (M)</button>
    <button onclick=\"markReject()\" style=\"background:#ff4f5e;border:none;color:#111;\">Not a match · R</button>
    <div id=\"counter\"></div>
    <div id=\"meta\"></div>
    <div id=\"controls\">
      <label>Max distance ≤ <span id=\"distanceValue\"></span></label>
      <input type=\"range\" id=\"distanceSlider\" min=\"0\" step=\"1\" />
      <button onclick=\"applyFilter()\">Reload</button>
    </div>
  </header>
  <main>
    <section class=\"panel\" id=\"panelA\">
      <h2 id=\"labelA\"></h2>
      <div class=\"img-wrap\"><img id=\"imgA\" draggable=\"false\" /></div>
      <a id=\"linkA\" target=\"_blank\">Reveal in Finder</a>
    </section>
    <section class=\"panel\" id=\"panelB\">
      <h2 id=\"labelB\"></h2>
      <div class=\"img-wrap\"><img id=\"imgB\" draggable=\"false\" /></div>
      <a id=\"linkB\" target=\"_blank\">Reveal in Finder</a>
    </section>
  </main>
  <div id=\"done\" style=\"display:none;\">All pairs have been reviewed ✨</div>
  <footer>Keys: M=match · R=not a match · →=next · ←=back · S=skip.</footer>
  <script>
    const pairsAll = {data_json};
    const summary = {summary_json};
    let filterThreshold = summary.max_distance;
    let pairs = [];
    let currentIndex = null;

    function setSliderDefaults() {{
      const slider = document.getElementById('distanceSlider');
      slider.max = Math.max(summary.max_distance, 1);
      slider.value = filterThreshold;
      document.getElementById('distanceValue').textContent = filterThreshold;
      slider.addEventListener('input', () => {{
        document.getElementById('distanceValue').textContent = slider.value;
      }});
    }}

    function applyFilter() {{
      const slider = document.getElementById('distanceSlider');
      filterThreshold = Number(slider.value);
      rebuildQueue();
    }}

    function rebuildQueue() {{
      pairs = pairsAll.filter((pair) => (pair.status || 'pending') === 'pending' && pair.distance <= filterThreshold);
      if (pairs.length === 0) {{
        currentIndex = null;
        document.getElementById('panelA').style.display = 'none';
        document.getElementById('panelB').style.display = 'none';
        document.getElementById('done').style.display = 'block';
        updateCounter();
        return;
      }}
      document.getElementById('panelA').style.display = '';
      document.getElementById('panelB').style.display = '';
      document.getElementById('done').style.display = 'none';
      currentIndex = 0;
      showCurrent();
    }}

    function updateCounter() {{
      const done = pairsAll.filter((pair) => pair.status === 'match' || pair.status === 'reject').length;
      const pending = pairsAll.length - done;
      document.getElementById('counter').textContent = 'Remaining ' + pending + ' of ' + summary.original + ' (done ' + done + ')';
      if (currentIndex === null || pairs.length === 0) {{
        document.getElementById('meta').textContent = '';
      }} else {{
        const pair = pairs[currentIndex];
        let statusLabel = '';
        if (pair.status === 'match') statusLabel = ' · marked MATCH';
        if (pair.status === 'reject') statusLabel = ' · marked NOT MATCH';
        document.getElementById('meta').textContent = 'Distance ' + pair.distance + ' · ' + (pair.reason || 'phash match') + statusLabel;
      }}
    }}

    function showCurrent() {{
      if (pairs.length === 0 || currentIndex === null) {{
        currentIndex = null;
        document.getElementById('panelA').style.display = 'none';
        document.getElementById('panelB').style.display = 'none';
        document.getElementById('done').style.display = 'block';
        updateCounter();
        return;
      }}
      if (currentIndex < 0) currentIndex = pairs.length - 1;
      if (currentIndex >= pairs.length) currentIndex = 0;
      const pair = pairs[currentIndex];
      document.getElementById('panelA').style.display = '';
      document.getElementById('panelB').style.display = '';
      document.getElementById('done').style.display = 'none';
      const left = pair.a;
      const right = pair.b;
      document.getElementById('labelA').textContent = left.bucket + ' (' + (left.source || 'unknown') + ')';
      document.getElementById('labelB').textContent = right.bucket + ' (' + (right.source || 'unknown') + ')';
      document.getElementById('imgA').src = '/image/' + encodeURIComponent(left.bucket);
      document.getElementById('imgB').src = '/image/' + encodeURIComponent(right.bucket);
      document.getElementById('linkA').href = left.uri;
      document.getElementById('linkB').href = right.uri;
      updateCounter();
    }}

    async function sendState(status) {{
      if (currentIndex === null || pairs.length === 0) return;
      const pair = pairs[currentIndex];
      const payload = {{ key: pair.key, status }};
      await fetch('/api/state', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify(payload)
      }});
    }}

    async function mark(status) {{
      if (currentIndex === null || pairs.length === 0) return;
      await sendState(status);
      const pair = pairs[currentIndex];
      pair.status = status;
      const allPair = pairsAll.find((p) => p.key === pair.key);
      if (allPair) allPair.status = status;
      pairs.splice(currentIndex, 1);
      if (pairs.length === 0) {{
        currentIndex = null;
        showCurrent();
        return;
      }}
      if (currentIndex >= pairs.length) currentIndex = 0;
      showCurrent();
    }}

    function markMatch() {{ mark('match'); }}
    function markReject() {{ mark('reject'); }}

    function skipPair() {{
      if (pairs.length === 0) return;
      currentIndex = (currentIndex + 1) % pairs.length;
      showCurrent();
    }}

    function prevPair() {{
      if (pairs.length === 0) return;
      currentIndex = (currentIndex - 1 + pairs.length) % pairs.length;
      showCurrent();
    }}

    document.addEventListener('keydown', (event) => {{
      if (event.key === 'ArrowRight') {{
        skipPair();
      }} else if (event.key === 'ArrowLeft') {{
        prevPair();
      }} else if (event.key.toLowerCase() === 'm') {{
        markMatch();
      }} else if (event.key.toLowerCase() === 'r') {{
        markReject();
      }} else if (event.key.toLowerCase() === 's') {{
        skipPair();
      }}
    }});

    setSliderDefaults();
    rebuildQueue();
  </script>
</body>
</html>
"""
        return html

    def serve_image(self, handler: http.server.BaseHTTPRequestHandler, bucket: str) -> None:
        path = self.image_paths.get(bucket)
        if not path or not path.exists():
            handler.send_error(404, "Image not found")
            return
        try:
            data = path.read_bytes()
        except OSError:
            handler.send_error(500, "Unable to read image")
            return
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        handler.send_response(200)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)


def _make_handler(context: ViewerContext):
    class ViewerHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:  # pragma: no cover
            return

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                payload = context.render_html().encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            elif self.path.startswith("/image/"):
                parsed = urllib.parse.urlparse(self.path)
                bucket = urllib.parse.unquote(parsed.path.split("/image/", 1)[1])
                context.serve_image(self, bucket)
            else:
                self.send_error(404, "Not found")

        def do_POST(self):
            if self.path != "/api/state":
                self.send_error(404, "Not found")
                return
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length)
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                self.send_error(400, "Invalid JSON")
                return
            key = data.get("key")
            status = data.get("status")
            if not isinstance(key, str) or status not in {"match", "reject", "pending"}:
                self.send_error(400, "Invalid payload")
                return
            context.update_state(key, status)
            self.send_response(204)
            self.end_headers()

    return ViewerHandler


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
                "path": str(image_path),
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
            key = _pair_key(bucket_a, bucket_b)
            pairs.append(
                {
                    "a": a,
                    "b": b,
                    "distance": int(row.get("distance", 0) or 0),
                    "reason": row.get("reason", ""),
                    "key": key,
                    "status": "pending",
                }
            )
    return pairs


def _pair_key(bucket_a: str, bucket_b: str) -> str:
    order = tuple(sorted((bucket_a, bucket_b)))
    return f"{order[0]}__{order[1]}"


if __name__ == "__main__":  # pragma: no cover
    app()
