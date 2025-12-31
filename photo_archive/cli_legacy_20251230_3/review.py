"""Launch the review UI for bucket before/after triage."""
from __future__ import annotations

import json
import logging
import mimetypes
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qs, urlparse

import typer

from PIL import Image

from archive_lib import config as config_mod, db as db_mod, log as log_mod
from archive_lib.decisions import DecisionStore
from archive_lib.reporting import BucketInfo, load_bucket_infos
from archive_lib.photo_transforms import PhotoTransformStore
from archive_lib.webimage import ensure_web_images
from archive_lib.ocr import perform_ocr, vision_available, timestamp

VOICE_STATE_DIR = Path.home() / "PhotoVoiceNotes"
VOICE_STATE_FILE = VOICE_STATE_DIR / "current_state.json"

app = typer.Typer(add_completion=False)


@app.command()
def main(
    source: Optional[str] = typer.Option(None, "--source", help="Limit to this source label"),
    include_all: bool = typer.Option(
        False, "--include-all", help="Include buckets without AI variants"
    ),
    limit: Optional[int] = typer.Option(None, "--limit", help="Limit number of buckets"),
    web_limit: Optional[int] = typer.Option(
        None,
        "--web-limit",
        help="Only rebuild web previews for the first N buckets (debug spot-check)",
    ),
    force_web: bool = typer.Option(False, "--force-web", help="Regenerate web images"),
    bucket_prefix: Optional[List[str]] = typer.Option(
        None,
        "--bucket-prefix",
        help="Only include specific bucket prefixes (repeatable)",
        rich_help_panel="Filtering",
    ),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging level"),
) -> None:
    """Build review assets, start a local server, and open the UI."""

    log_mod.setup_logging(log_level)
    logger = logging.getLogger("cli.review")
    cfg = config_mod.load_config()
    conn = db_mod.connect(cfg.db_path)
    infos = load_bucket_infos(conn, cfg, source=source)
    if not infos:
        typer.echo("No buckets found for the requested filters", err=True)
        raise typer.Exit(code=1)

    if bucket_prefix:
        requested = set(bucket_prefix)
        infos = [info for info in infos if info.bucket_prefix in requested]
        if not infos:
            typer.echo("No buckets match the requested bucket prefixes", err=True)
            raise typer.Exit(code=1)

    typer.echo(f"Loaded {len(infos)} buckets; generating web previews…")
    web_targets = infos[:web_limit] if web_limit else infos
    counts = ensure_web_images(
        web_targets,
        cfg.buckets_dir,
        logger=logger,
        force=force_web,
        dirty_only=not force_web,
        update_state=True,
    )
    typer.echo(
        "Web images: "
        f"created={counts['created']} skipped={counts['skipped']} "
        f"missing={counts['missing_source']} clean={counts['clean']}"
    )

    decisions_path = cfg.config_dir / "ai_choices.csv"
    decision_store = DecisionStore(decisions_path)
    photo_transform_store = PhotoTransformStore(cfg.config_dir / "photo_transforms.json")
    dataset = _build_dataset(cfg, infos, decision_store.all(), include_all=include_all, limit=limit)
    if not dataset["buckets"]:
        typer.echo("No eligible buckets to review after filtering", err=True)
        raise typer.Exit(code=1)

    review_dir = _write_review_assets(cfg, dataset)
    server = _start_server(cfg, decision_store, photo_transform_store)
    url = f"http://127.0.0.1:{server.server_address[1]}/views/review/index.html"
    typer.echo(f"Review server running at {url}")
    webbrowser.open(url)
    typer.echo("Press Ctrl+C to stop…")
    _wait_forever(server)


def _build_dataset(
    cfg: config_mod.AppConfig,
    infos,
    decisions: Dict[str, object],
    *,
    include_all: bool,
    limit: Optional[int],
) -> Dict[str, object]:
    review_root = cfg.staging_root / "02_WORKING_BUCKETS"
    voice_root = cfg.repo_root / "02_WORKING_BUCKETS" / "voice_sessions" / "transcripts"
    fastfoto_links, skip_back_prefixes = _detect_fastfoto_links(infos)
    duplicate_clusters = _load_duplicate_clusters(cfg)
    buckets_data: List[Dict[str, object]] = []
    entry_lookup: Dict[str, Dict[str, object]] = {}
    for info in sorted(infos, key=lambda item: (item.source, item.bucket_prefix)):
        if info.bucket_prefix in skip_back_prefixes:
            continue
        bucket_dir = cfg.buckets_dir / f"bkt_{info.bucket_prefix}"
        derived_dir = bucket_dir / "derived"
        web_front = derived_dir / "web_front.jpg"
        web_ai = derived_dir / "web_ai.jpg"
        thumb_front = derived_dir / "thumb_front.jpg"
        thumb_ai = derived_dir / "thumb_ai_front_v1.jpg"
        has_ai = web_ai.exists()
        if not include_all and not has_ai:
            continue
        variant_map = _variant_index(info.variants)
        finder_front_variant = variant_map.get("raw_front") or variant_map.get("proxy_front")
        display_back_variant = variant_map.get("proxy_back") or variant_map.get("raw_back")
        finder_back_variant = variant_map.get("raw_back") or variant_map.get("proxy_back")
        ai_variant = variant_map.get("ai_front_v1")
        auto_ocr = info.data.get("auto_ocr") if isinstance(info.data, dict) else {}
        human_ocr = info.data.get("human_ocr") if isinstance(info.data, dict) else {}
        voice_transcripts = info.data.get("voice_transcripts") if isinstance(info.data, dict) else []
        normalized_voice: List[Dict[str, object]] = []
        if isinstance(voice_transcripts, list):
            for record in voice_transcripts:
                if not isinstance(record, dict):
                    continue
                normalized_voice.append(
                    {
                        "id": record.get("id"),
                        "speaker": record.get("speaker"),
                        "session_id": record.get("session_id"),
                        "created_at": record.get("created_at"),
                        "entries": record.get("entries"),
                        "note_block": record.get("note_block"),
                    }
                )
        disk_voice = _load_voice_transcripts_from_disk(voice_root, info.bucket_prefix)
        if disk_voice:
            normalized_voice = _merge_voice_transcripts(normalized_voice, disk_voice)
        review_note = ""
        ocr_status = ""
        if isinstance(info.data, dict):
            review_note = str(info.data.get("review_note") or "")
            ocr_status = str(info.data.get("ocr_status") or "")
        if not ocr_status and auto_ocr:
            ocr_status = "machine"
        linked_back = fastfoto_links.get(info.bucket_prefix)
        linked_back_assets = None
        if linked_back and not display_back_variant:
            linked_back_assets = _linked_back_assets(cfg, linked_back)
            if linked_back_assets:
                display_back_variant = True
                finder_back_variant = linked_back_assets.get("finder_variant")
        has_back = bool(display_back_variant)
        auto_ocr_payload = dict(auto_ocr) if isinstance(auto_ocr, dict) else {}
        if linked_back and has_back and not auto_ocr_payload.get("back_text"):
            back_auto = linked_back.data.get("auto_ocr") if isinstance(linked_back.data, dict) else {}
            if back_auto and back_auto.get("front_text"):
                auto_ocr_payload["back_text"] = back_auto.get("front_text")
        entry = {
            "bucket_prefix": info.bucket_prefix,
            "bucket_id": info.bucket_id,
            "source": info.source,
            "group_key": info.group_key,
            "web_front": _relpath_if_exists(web_front, review_root),
            "web_ai": _relpath_if_exists(web_ai, review_root),
            "web_back": _relpath_if_exists(derived_dir / "web_back.jpg", review_root)
            if not linked_back_assets
            else linked_back_assets.get("web"),
            "thumb_front": _relpath_if_exists(thumb_front, review_root),
            "thumb_ai": _relpath_if_exists(thumb_ai, review_root),
            "thumb_back": _relpath_if_exists(derived_dir / "thumb_back.jpg", review_root)
            if not linked_back_assets
            else linked_back_assets.get("thumb"),
            "has_ai": has_ai,
            "has_back": has_back,
            "caption": _extract_caption(info.data),
            "keywords": _extract_keywords(info.data),
            "photos_uuid": _extract_uuid(info.data),
            "orientation": _build_orientation_meta(info, variant_map.get("raw_front")),
            "finder_paths": _build_finder_paths(
                finder_front_variant,
                ai_variant,
                finder_back_variant,
            ),
            "auto_ocr": auto_ocr_payload,
            "human_ocr": human_ocr or {},
            "voice_transcripts": normalized_voice,
            "ocr_status": ocr_status,
            "review_note": review_note,
            "linked_back_bucket": linked_back.bucket_prefix if linked_back else None,
        }
        decision = decisions.get(info.bucket_prefix)
        if decision:
            entry["decision"] = decision.choice
            entry["note"] = decision.note
        else:
            entry["note"] = review_note
        buckets_data.append(entry)
        entry_lookup[info.bucket_prefix] = entry
        if limit and len(buckets_data) >= limit:
            break
    _attach_duplicate_metadata(buckets_data, duplicate_clusters, entry_lookup)
    return {
        "generated_at": time.time(),
        "count": len(buckets_data),
        "buckets": buckets_data,
    }


def _extract_caption(data: Dict[str, object]) -> str:
    photos = data.get("photos_asset") if isinstance(data, dict) else {}
    if not isinstance(photos, dict):
        return ""
    return str(photos.get("description") or photos.get("caption") or "")


def _extract_keywords(data: Dict[str, object]) -> List[str]:
    photos = data.get("photos_asset") if isinstance(data, dict) else {}
    if not isinstance(photos, dict):
        return []
    keywords = photos.get("keywords") or []
    if isinstance(keywords, list):
        return [str(item) for item in keywords]
    return []


def _extract_uuid(data: Dict[str, object]) -> str:
    photos = data.get("photos_asset") if isinstance(data, dict) else {}
    if not isinstance(photos, dict):
        return ""
    return str(photos.get("uuid") or photos.get("id") or "")


def _load_voice_transcripts_from_disk(root: Path, bucket_prefix: str) -> List[Dict[str, object]]:
    bucket_dir = root / bucket_prefix
    records: List[Dict[str, object]] = []
    if not bucket_dir.exists():
        return records
    for item in sorted(bucket_dir.glob("*.json")):
        try:
            data = json.loads(item.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict):
            records.append(
                {
                    "id": data.get("id"),
                    "speaker": data.get("speaker"),
                    "session_id": data.get("session_id"),
                    "created_at": data.get("created_at"),
                    "entries": data.get("entries"),
                    "note_block": data.get("note_block"),
                }
            )
    return records


def _merge_voice_transcripts(
    existing: List[Dict[str, object]],
    additional: List[Dict[str, object]],
) -> List[Dict[str, object]]:
    merged: List[Dict[str, object]] = []
    seen_ids: Set[str] = set()
    seen_blocks: Set[str] = set()

    def _add(record: Dict[str, object]) -> None:
        if not isinstance(record, dict):
            return
        record_id = str(record.get("id") or "")
        block = str(record.get("note_block") or "").strip()
        if record_id and record_id in seen_ids:
            return
        if block and block in seen_blocks:
            return
        if record_id:
            seen_ids.add(record_id)
        if block:
            seen_blocks.add(block)
        merged.append(record)

    for rec in existing:
        _add(rec)
    for rec in additional:
        _add(rec)
    return merged


def _variant_index(variants) -> Dict[str, object]:
    index: Dict[str, object] = {}
    for variant in variants or []:
        role = getattr(variant, "role", None) or (variant.get("role") if isinstance(variant, dict) else None)
        if role and role not in index:
            index[role] = variant
    return index


def _build_orientation_meta(info, raw_variant) -> Dict[str, Optional[int]]:
    photos = info.data.get("photos_asset") if isinstance(info.data, dict) else {}
    if not isinstance(photos, dict):
        photos = {}
    return {
        "photos_orientation": _normalize_orientation(photos.get("orientation")),
        "photos_original_orientation": _normalize_orientation(photos.get("original_orientation")),
        "raw_exif_orientation": _read_variant_exif(raw_variant),
    }


def _read_variant_exif(variant) -> Optional[int]:
    path_str = None
    if variant is None:
        return None
    if isinstance(variant, dict):
        path_str = variant.get("path")
    else:
        path_str = getattr(variant, "path", None)
    if not path_str:
        return None
    path = Path(str(path_str))
    if not path.exists():
        return None
    try:
        with Image.open(path) as img:
            exif = img.getexif()
    except Exception:  # pragma: no cover
        return None
    if not exif:
        return None
    value = exif.get(0x0112)
    return int(value) if isinstance(value, (int,)) else None


def _normalize_orientation(value: object) -> Optional[int]:
    if value is None:
        return None
    try:
        orientation = int(value)
    except (TypeError, ValueError):
        return None
    if 1 <= orientation <= 8:
        return orientation
    return None


def _relpath_if_exists(path: Path, root: Path) -> Optional[str]:
    if not path.exists():
        return None
    rel = os.path.relpath(path, root).replace(os.sep, "/")
    return f"/{rel}"


def _variant_path(variant) -> Optional[str]:
    if not variant:
        return None
    path_value = variant.get("path") if isinstance(variant, dict) else getattr(variant, "path", None)
    if not path_value:
        return None
    return str(Path(path_value))


def _build_finder_paths(front_variant, ai_variant, back_variant) -> Dict[str, Optional[str]]:
    return {
        "original": _variant_path(front_variant),
        "ai": _variant_path(ai_variant),
        "back": _variant_path(back_variant),
    }


def _detect_fastfoto_links(infos) -> Tuple[Dict[str, BucketInfo], set]:
    front_by_base: Dict[str, List[BucketInfo]] = {}
    back_by_base: Dict[str, List[BucketInfo]] = {}
    for info in infos:
        original = _fastfoto_original(info)
        if not original:
            continue
        base, is_back = _fastfoto_base(original)
        if not base:
            continue
        if is_back:
            back_by_base.setdefault(base, []).append(info)
        else:
            front_by_base.setdefault(base, []).append(info)
    links: Dict[str, BucketInfo] = {}
    back_skip: set = set()
    for base, front_list in front_by_base.items():
        back_list = back_by_base.get(base)
        if not back_list or len(back_list) != 1 or len(front_list) != 1:
            continue
        front = front_list[0]
        back = back_list[0]
        links[front.bucket_prefix] = back
        back_skip.add(back.bucket_prefix)
    return links, back_skip


def _load_duplicate_clusters(cfg: config_mod.AppConfig) -> Dict[str, Dict[str, object]]:
    state_path = cfg.reports_dir / "phash_test" / "phash_review_state.json"
    if not state_path.exists():
        return {}
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    graph: Dict[str, Set[str]] = {}
    for raw_key, raw_status in data.items():
        status = str(raw_status).lower()
        if status != "match":
            continue
        if not isinstance(raw_key, str) or "__" not in raw_key:
            continue
        left, right = raw_key.split("__", 1)
        left = left.strip()
        right = right.strip()
        if not left or not right or left == right:
            continue
        graph.setdefault(left, set()).add(right)
        graph.setdefault(right, set()).add(left)
    clusters: Dict[str, Dict[str, object]] = {}
    visited: Set[str] = set()
    for node in graph.keys():
        if node in visited:
            continue
        stack = [node]
        component: Set[str] = set()
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            component.add(current)
            for neighbor in graph.get(current, set()):
                if neighbor not in visited:
                    stack.append(neighbor)
        if len(component) < 2:
            continue
        group_id = sorted(component)[0]
        members_sorted = sorted(component)
        for prefix in component:
            peers = [member for member in members_sorted if member != prefix]
            clusters[prefix] = {
                "group_id": group_id,
                "group_size": len(component),
                "members": peers,
            }
    return clusters


def _attach_duplicate_metadata(
    entries: List[Dict[str, object]],
    clusters: Optional[Dict[str, Dict[str, object]]],
    entry_lookup: Dict[str, Dict[str, object]],
) -> None:
    if not clusters:
        return
    for entry in entries:
        prefix = entry.get("bucket_prefix")
        if not isinstance(prefix, str):
            continue
        cluster = clusters.get(prefix)
        if not cluster:
            continue
        peers_data: List[Dict[str, object]] = []
        for peer_prefix in cluster.get("members", []):
            peer_entry = entry_lookup.get(peer_prefix)
            if not peer_entry:
                continue
            peers_data.append(
                {
                    "bucket_prefix": peer_prefix,
                    "source": peer_entry.get("source"),
                    "has_ai": bool(peer_entry.get("has_ai")),
                    "has_back": bool(peer_entry.get("has_back")),
                    "web_front": peer_entry.get("web_front") or peer_entry.get("thumb_front"),
                    "decision": peer_entry.get("decision"),
                }
            )
        if peers_data:
            entry["duplicates"] = {
                "group_id": cluster.get("group_id"),
                "group_size": cluster.get("group_size"),
                "peers": peers_data,
            }


def _fastfoto_original(info: BucketInfo) -> str:
    data = info.data if isinstance(info.data, dict) else {}
    photos = data.get("photos_asset")
    if not isinstance(photos, dict):
        return ""
    return str(photos.get("original_filename") or "")


def _fastfoto_base(name: str) -> Tuple[str, bool]:
    lower = name.lower()
    if not lower.startswith("fastfoto_"):
        return ("", False)
    if lower.endswith("_b.tif"):
        return lower[:-len("_b.tif")] + ".tif", True
    if lower.endswith(".tif"):
        return lower, False
    return (lower, False)


def _linked_back_assets(cfg: config_mod.AppConfig, back_info: BucketInfo) -> Dict[str, Optional[str]]:
    bucket_dir = cfg.buckets_dir / f"bkt_{back_info.bucket_prefix}"
    web_front = bucket_dir / "derived" / "web_front.jpg"
    thumb_front = bucket_dir / "derived" / "thumb_front.jpg"
    variant_map = _variant_index(back_info.variants)
    finder_variant = variant_map.get("raw_front") or variant_map.get("proxy_front")
    review_root = cfg.staging_root / "02_WORKING_BUCKETS"
    return {
        "web": _relpath_if_exists(web_front, review_root),
        "thumb": _relpath_if_exists(thumb_front, review_root),
        "finder_variant": finder_variant,
    }


def _write_review_assets(cfg: config_mod.AppConfig, dataset: Dict[str, object]) -> Path:
    views_root = cfg.staging_root / "02_WORKING_BUCKETS" / "views"
    review_dir = views_root / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    templates_dir = cfg.repo_root / "templates" / "review"
    for filename in ("index.html", "styles.css", "review_app.js"):
        src = templates_dir / filename
        dst = review_dir / filename
        dst.write_bytes(src.read_bytes())
    data_js = review_dir / "review_data.js"
    payload = json.dumps(dataset, ensure_ascii=False)
    data_js.write_text(f"window.REVIEW_DATA = {payload};\n", encoding="utf-8")
    return review_dir


def _write_state_snapshot(payload: Dict[str, object]) -> None:
    VOICE_STATE_DIR.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2)
    temp_path = VOICE_STATE_FILE.with_suffix(".tmp")
    temp_path.write_text(encoded, encoding="utf-8")
    os.replace(temp_path, VOICE_STATE_FILE)


def _start_server(
    cfg: config_mod.AppConfig,
    decision_store: DecisionStore,
    photo_transform_store: PhotoTransformStore,
) -> ThreadingHTTPServer:
    base_dir = cfg.staging_root / "02_WORKING_BUCKETS"
    handler_cls = partial(
        ReviewRequestHandler,
        directory=str(base_dir),
        decision_store=decision_store,
        photo_transform_store=photo_transform_store,
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)  # ephemeral port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _wait_forever(server: ThreadingHTTPServer) -> None:
    try:
        signal.pause()
    except AttributeError:
        # Windows does not have pause(); fall back to sleep loop
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()


class ReviewRequestHandler(SimpleHTTPRequestHandler):
    def __init__(
        self,
        *args,
        directory: str,
        decision_store: DecisionStore,
        photo_transform_store: PhotoTransformStore,
        **kwargs,
    ) -> None:
        self.decision_store = decision_store
        self.photo_transform_store = photo_transform_store
        super().__init__(*args, directory=directory, **kwargs)

    def do_GET(self) -> None:  # pragma: no cover - exercised manually
        parsed = urlparse(self.path)
        if parsed.path == "/api/fullres":
            self._serve_fullres(parsed)
            return
        if parsed.path == "/api/photo/transform":
            self._serve_photo_transform(parsed)
            return
        super().do_GET()

    def do_POST(self) -> None:  # pragma: no cover - exercised manually
        endpoint = self.path.rstrip("/")
        if endpoint == "/api/decision":
            self._handle_decision()
        elif endpoint == "/api/reveal":
            self._handle_reveal()
        elif endpoint == "/api/ocr":
            self._handle_ocr()
        elif endpoint == "/api/state_update":
            self._handle_state_update()
        elif endpoint == "/api/photo/transform":
            self._handle_photo_transform()
        else:
            self.send_error(404, "Unknown endpoint")

    def _handle_decision(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return
        bucket_prefix = data.get("bucket_prefix")
        note = data.get("note") or ""
        ocr_status = (data.get("ocr_status") or "").strip()
        if not bucket_prefix:
            self.send_error(400, "Missing bucket_prefix")
            return
        try:
            if data.get("clear"):
                self.decision_store.clear(bucket_prefix)
                self._update_sidecar_metadata(bucket_prefix, note="", ocr_status=ocr_status)
                self._write_json({"status": "cleared"})
                return
            choice = data.get("choice")
            decision = self.decision_store.update(bucket_prefix, choice, note)
            self._update_sidecar_metadata(bucket_prefix, note=note, ocr_status=ocr_status)
            self._write_json({"status": "ok", "decision": decision.__dict__})
        except ValueError as exc:  # invalid choice
            self.send_error(400, str(exc))

    def _handle_reveal(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return
        path_value = (data.get("path") or "").strip()
        if not path_value:
            self.send_error(400, "Missing path")
            return
        target = Path(path_value).expanduser()
        if not target.exists():
            self.send_error(404, "Path not found")
            return
        try:
            self._reveal_path(target)
        except RuntimeError as exc:
            self.send_error(500, str(exc))
            return
        self._write_json({"status": "ok"})

    def _reveal_path(self, target: Path) -> None:
        if sys.platform == "darwin":
            cmd = ["open", "-R", str(target)]
        else:
            opener = shutil.which("xdg-open")
            if not opener:
                raise RuntimeError("Reveal not supported on this platform")
            reveal_target = target if target.is_dir() else target.parent
            cmd = [opener, str(reveal_target)]
        try:
            subprocess.run(cmd, check=False)
        except OSError as exc:  # pragma: no cover
            raise RuntimeError(f"Failed to reveal file: {exc}") from exc

    def _handle_ocr(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return
        bucket_prefix = (data.get("bucket_prefix") or "").strip()
        variant = (data.get("variant") or "raw_back").strip() or "raw_back"
        if not bucket_prefix:
            self.send_error(400, "Missing bucket_prefix")
            return
        roles = [variant]
        if variant == "raw_back":
            roles.append("proxy_back")
        elif variant == "proxy_back":
            roles.append("raw_back")
        image_path = self._find_variant_path(bucket_prefix, roles)
        if image_path is None:
            self.send_error(404, "Requested image variant not found")
            return
        if not vision_available():  # pragma: no cover
            self.send_error(
                500, "Apple Vision OCR unavailable. Install pyobjc-core and pyobjc-framework-Vision."
            )
            return
        try:
            text = perform_ocr(image_path)
        except RuntimeError as exc:
            self.send_error(500, str(exc))
            return
        self._write_json({"status": "ok", "text": text})

    def _handle_state_update(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return
        bucket_id = (data.get("bucketId") or "").strip()
        if not bucket_id:
            self._write_json({"status": "ignored"})
            return
        session_id = (data.get("sessionId") or "").strip()
        snapshot = {
            "bucketId": bucket_id,
            "bucketSource": data.get("bucketSource"),
            "imageId": (data.get("imageId") or "").strip() or None,
            "variant": data.get("variant"),
            "primaryVariant": data.get("primaryVariant"),
            "compareVariant": data.get("compareVariant"),
            "compareMode": data.get("compareMode"),
            "path": data.get("path"),
            "primaryPath": data.get("primaryPath"),
            "comparePath": data.get("comparePath"),
            "webPath": data.get("webPath"),
            "index": data.get("index"),
            "total": data.get("total"),
            "bucketPosition": data.get("bucketPosition"),
            "timestamp": int(data.get("timestamp") or time.time() * 1000),
            "received_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "reason": data.get("reason"),
            "noteFlag": bool(data.get("noteFlag")),
            "sessionId": session_id or None,
        }
        try:
            _write_state_snapshot(snapshot)
        except OSError as exc:
            logging.getLogger("cli.review").warning("State snapshot write failed: %s", exc)
            self.send_error(500, "Failed to persist recorder state")
            return
        self._write_json({"status": "ok"})

    def _serve_photo_transform(self, parsed) -> None:
        params = parse_qs(parsed.query)
        bucket_prefix = (params.get("bucket_prefix") or [""])[0].strip()
        if not bucket_prefix:
            self.send_error(400, "bucket_prefix is required")
            return
        transform = self.photo_transform_store.get_transform(bucket_prefix)
        payload = {"status": "ok", "bucket_prefix": bucket_prefix}
        payload.update(transform)
        self._write_json(payload)

    def _handle_photo_transform(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return
        bucket_prefix = (data.get("bucket_prefix") or "").strip()
        side = (data.get("side") or "").strip().lower()
        if not bucket_prefix:
            self.send_error(400, "bucket_prefix is required")
            return
        if side not in {"front", "back"}:
            self.send_error(400, "side must be 'front' or 'back'")
            return
        rotation = data.get("rotate")
        try:
            value = self.photo_transform_store.set_rotation(bucket_prefix, side, rotation)
        except ValueError as exc:
            self.send_error(400, str(exc))
            return
        self._write_json({"status": "ok", "bucket_prefix": bucket_prefix, "side": side, "rotate": value})

    def log_message(self, format: str, *args) -> None:  # pragma: no cover
        return  # Silence default logging

    def _write_json(self, data: Dict[str, object]) -> None:
        encoded = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _serve_fullres(self, parsed):
        params = parse_qs(parsed.query)
        bucket_prefix = (params.get("bucket") or [""])[0]
        variant = (params.get("variant") or [""])[0]
        if not bucket_prefix or variant not in {"raw_front", "ai_front_v1"}:
            self.send_error(400, "Missing or invalid parameters")
            return
        bucket_dir = Path(self.directory) / "buckets" / f"bkt_{bucket_prefix}"
        sidecar_path = bucket_dir / "sidecar.json"
        if not sidecar_path.exists():
            self.send_error(404, "Bucket not found")
            return
        try:
            sidecar = json.loads(sidecar_path.read_text())
        except json.JSONDecodeError:
            self.send_error(500, "Invalid sidecar metadata")
            return
        variants = sidecar.get("data", {}).get("variants", [])
        target = None
        for candidate in variants:
            if candidate.get("role") == variant:
                target = candidate
                break
        if not target:
            self.send_error(404, f"No {variant} variant available")
            return
        source = Path(str(target.get("path", "")))
        if not source.exists() or not source.is_file():
            self.send_error(404, "Full-resolution source missing")
            return
        mime = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        try:
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(source.stat().st_size))
            self.end_headers()
            with source.open("rb") as handle:
                shutil.copyfileobj(handle, self.wfile)
        except OSError as exc:  # pragma: no cover
            self.send_error(500, f"Failed to stream file: {exc}")

    def _find_variant_path(self, bucket_prefix: str, roles: List[str]) -> Optional[Path]:
        bucket_dir = Path(self.directory) / "buckets" / f"bkt_{bucket_prefix}"
        sidecar_path = bucket_dir / "sidecar.json"
        if not sidecar_path.exists():
            return None
        try:
            sidecar = json.loads(sidecar_path.read_text())
        except json.JSONDecodeError:
            return None
        variants = sidecar.get("data", {}).get("variants", [])
        for role in roles:
            for candidate in variants:
                if candidate.get("role") != role:
                    continue
                path_str = candidate.get("path")
                if not path_str:
                    continue
                path = Path(str(path_str))
                if path.exists():
                    return path
        return None

    def _update_sidecar_metadata(
        self, bucket_prefix: str, note: Optional[str] = None, ocr_status: Optional[str] = None
    ) -> None:
        bucket_dir = Path(self.directory) / "buckets" / f"bkt_{bucket_prefix}"
        sidecar_path = bucket_dir / "sidecar.json"
        if not sidecar_path.exists():
            return
        try:
            sidecar = json.loads(sidecar_path.read_text())
        except json.JSONDecodeError:
            return
        payload = sidecar.setdefault("data", {})
        if note is not None:
            if note:
                payload["review_note"] = note
            else:
                payload.pop("review_note", None)
        if ocr_status:
            payload["ocr_status"] = ocr_status
            if note:
                payload["human_ocr"] = {
                    "text": note,
                    "updated_at": timestamp(),
                }
        elif ocr_status == "":
            payload.pop("ocr_status", None)
        try:
            sidecar_path.write_text(json.dumps(sidecar, ensure_ascii=False, indent=2))
        except OSError:
            pass


def run() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    run()
