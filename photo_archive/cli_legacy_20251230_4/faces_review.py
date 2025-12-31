"""Serve a lightweight UI for labeling detected faces."""
from __future__ import annotations

import json
import logging
import os
import signal
import threading
import time
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Optional

import typer

from archive_lib import config as config_mod, db as db_mod, log as log_mod
from archive_lib.face_tags import FaceTag, FaceTagStore

app = typer.Typer(add_completion=False)


@app.command()
def main(
    source: Optional[str] = typer.Option(None, "--source", help="Limit to a single source label"),
    min_confidence: float = typer.Option(
        0.35, "--min-confidence", min=0.0, max=1.0, help="Only include detections at or above this score"
    ),
    limit: Optional[int] = typer.Option(None, "--limit", help="Only include the first N faces"),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging level"),
) -> None:
    """Build the face dataset and launch the browser-based labeling tool."""

    if min_confidence < 0 or min_confidence > 1:
        raise typer.BadParameter("--min-confidence must be between 0 and 1")

    log_mod.setup_logging(log_level)
    logger = logging.getLogger("cli.faces_review")
    cfg = config_mod.load_config()
    conn = db_mod.connect(cfg.db_path)

    tag_store = FaceTagStore(cfg.config_dir / "face_tags.csv")
    dataset = _build_dataset(conn, cfg, tag_store.all(), source=source, min_confidence=min_confidence, limit=limit)
    if not dataset["faces"]:
        typer.echo("No faces matched the requested filters", err=True)
        raise typer.Exit(code=1)

    review_dir = _write_face_assets(cfg, dataset)
    typer.echo(f"Wrote face dataset to {review_dir}")

    server = _start_server(cfg, tag_store, logger=logger)
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}/views/faces/index.html"
    typer.echo(f"Face review server running at {url}")
    try:
        webbrowser.open(url)
    except Exception as exc:  # pragma: no cover
        logger.debug("Failed to open browser automatically: %s", exc)
    typer.echo("Press Ctrl+C to stop…")
    _wait_forever(server)


def _build_dataset(
    conn,
    cfg: config_mod.AppConfig,
    tags: Dict[str, FaceTag],
    *,
    source: Optional[str],
    min_confidence: float,
    limit: Optional[int],
) -> Dict[str, object]:
    sql = """
        SELECT
            f.bucket_id,
            f.face_index,
            f.confidence,
            f.left,
            f.top,
            f.width,
            f.height,
            b.bucket_prefix,
            b.source
        FROM face_embeddings AS f
        JOIN buckets AS b ON b.bucket_id = f.bucket_id
        WHERE f.variant_role IN ('raw_front', 'proxy_front')
          AND f.confidence >= ?
    """
    params: List[object] = [min_confidence]
    if source:
        sql += " AND b.source = ?"
        params.append(source)
    sql += " ORDER BY f.confidence DESC, b.source ASC, b.bucket_prefix ASC, f.face_index ASC"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    buckets_root = cfg.staging_root / "02_WORKING_BUCKETS"
    faces_dir = cfg.buckets_dir

    faces: List[Dict[str, object]] = []
    sources = set()
    for row in rows:
        bucket_prefix = row["bucket_prefix"]
        image_path = _resolve_image_path(faces_dir, bucket_prefix)
        if not image_path:
            continue
        rel_path = _relpath(image_path, buckets_root)
        face_id = f"{bucket_prefix}:{row['face_index']}"
        tag = tags.get(face_id)
        faces.append(
            {
                "face_id": face_id,
                "bucket_prefix": bucket_prefix,
                "bucket_id": row["bucket_id"],
                "face_index": int(row["face_index"]),
                "source": row["source"],
                "confidence": float(row["confidence"] or 0.0),
                "bbox": {
                    "left": float(row["left"] or 0.0),
                    "top": float(row["top"] or 0.0),
                    "width": float(row["width"] or 0.0),
                    "height": float(row["height"] or 0.0),
                },
                "image": rel_path,
                "label": getattr(tag, "label", ""),
                "note": getattr(tag, "note", ""),
                "updated_at": getattr(tag, "updated_at_utc", ""),
            }
        )
        sources.add(row["source"])

    return {
        "generated_at": time.time(),
        "count": len(faces),
        "faces": faces,
        "sources": sorted(sources),
        "min_confidence": min_confidence,
    }


def _resolve_image_path(buckets_dir: Path, bucket_prefix: str) -> Optional[Path]:
    bucket_dir = buckets_dir / f"bkt_{bucket_prefix}"
    derived = bucket_dir / "derived"
    for candidate in (
        derived / "web_front.jpg",
        derived / "thumb_front.jpg",
        derived / "web_ai.jpg",
        derived / "thumb_ai_front_v1.jpg",
    ):
        if candidate.exists():
            return candidate
    return None


def _relpath(path: Path, root: Path) -> str:
    rel = os.path.relpath(path, root).replace(os.sep, "/")
    if not rel.startswith("/"):
        rel = f"/{rel}"
    return rel


def _write_face_assets(cfg: config_mod.AppConfig, dataset: Dict[str, object]) -> Path:
    views_root = cfg.staging_root / "02_WORKING_BUCKETS" / "views"
    faces_dir = views_root / "faces"
    faces_dir.mkdir(parents=True, exist_ok=True)
    templates_dir = cfg.repo_root / "templates" / "faces"
    for filename in ("index.html", "styles.css", "faces_app.js"):
        src = templates_dir / filename
        dst = faces_dir / filename
        dst.write_bytes(src.read_bytes())
    data_js = faces_dir / "faces_data.js"
    payload = json.dumps(dataset, ensure_ascii=False)
    data_js.write_text(f"window.FACES_DATA = {payload};\n", encoding="utf-8")
    return faces_dir


def _start_server(cfg: config_mod.AppConfig, tag_store: FaceTagStore, *, logger: logging.Logger) -> ThreadingHTTPServer:
    base_dir = cfg.staging_root / "02_WORKING_BUCKETS"
    handler_cls = partial(FaceReviewRequestHandler, directory=str(base_dir), tag_store=tag_store, logger=logger)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _wait_forever(server: ThreadingHTTPServer) -> None:
    try:
        signal.pause()
    except AttributeError:
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()


class FaceReviewRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory: str, tag_store: FaceTagStore, logger: logging.Logger, **kwargs) -> None:
        self.tag_store = tag_store
        self.logger = logger
        super().__init__(*args, directory=directory, **kwargs)

    def do_POST(self) -> None:  # pragma: no cover - exercised manually
        if self.path.rstrip("/") != "/api/face-tag":
            self.send_error(404, "Unknown endpoint")
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON payload")
            return

        face_id = (payload.get("face_id") or "").strip()
        if not face_id:
            self.send_error(400, "Missing face_id")
            return
        if payload.get("clear"):
            self.tag_store.clear(face_id)
            self._write_json({"status": "cleared", "face_id": face_id})
            return

        label = (payload.get("label") or "").strip()
        bucket_prefix = (payload.get("bucket_prefix") or "").strip()
        try:
            face_index = int(payload.get("face_index") or 0)
        except (TypeError, ValueError):
            face_index = 0
        note = (payload.get("note") or "").strip()
        try:
            tag = self.tag_store.update(face_id, bucket_prefix, face_index, label, note)
        except ValueError as exc:
            self.send_error(400, str(exc))
            return
        self._write_json(
            {
                "status": "ok",
                "tag": {
                    "face_id": tag.face_id,
                    "label": tag.label,
                    "note": tag.note,
                    "updated_at_utc": tag.updated_at_utc,
                },
            }
        )

    def log_message(self, format: str, *args) -> None:  # pragma: no cover
        if self.logger:
            self.logger.debug("Server: " + format, *args)

    def _write_json(self, data: Dict[str, object]) -> None:
        encoded = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def run() -> None:  # pragma: no cover
    typer.run(main)


if __name__ == "__main__":  # pragma: no cover
    run()
