"""Interactive queue for confirming face identities one by one."""
from __future__ import annotations

import hashlib
import json
import logging
import signal
import threading
import time
import uuid
import webbrowser
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple
from urllib.parse import parse_qs, urlparse

import typer
import numpy as np
from PIL import Image

from archive_lib import config as config_mod, db as db_mod, log as log_mod, orientation as orientation_mod
from archive_lib.faces import FaceRecognizer
from archive_lib.face_clusters import FaceClusterBuilder, FaceClusterStore
from archive_lib.face_matcher import FaceMatcher, FaceRecord, load_face_records
from archive_lib.face_tags import FaceTagStore
from archive_lib.face_votes import FaceVoteStore
from archive_lib.face_ignores import FaceIgnoreStore
from archive_lib.photo_transforms import PhotoTransformStore

CLUSTER_CACHE_FILENAME = "face_clusters.json"
CLUSTER_DEFAULT_MIN_FACES = 4
CLUSTER_DEFAULT_SIMILARITY = 0.83
CLUSTER_DEFAULT_BITS_PER_BAND = 12
CLUSTER_DEFAULT_BAND_COUNT = 6
CLUSTER_DEFAULT_MAX_BUCKET = 800


class FacePeopleStore:
    """Simple JSON-backed metadata for pins/groups/ignored labels."""

    VERSION = 1

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()
        self._data = {
            "version": self.VERSION,
            "updated_at": int(time.time()),
            "labels": {},
            "groups": {},
        }
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        labels = payload.get("labels")
        groups = payload.get("groups")
        self._data["labels"] = labels if isinstance(labels, dict) else {}
        self._data["groups"] = groups if isinstance(groups, dict) else {}
        version = payload.get("version")
        if isinstance(version, int) and version > 0:
            self._data["version"] = version
        updated = payload.get("updated_at")
        if isinstance(updated, (int, float)):
            self._data["updated_at"] = int(updated)

    def label_metadata(self, label: str) -> Dict[str, object]:
        entry = self._data.get("labels", {}).get(label)
        if not isinstance(entry, dict):
            return {"pinned": False, "group": "", "ignored": False}
        return {
            "pinned": bool(entry.get("pinned")),
            "group": str(entry.get("group") or ""),
            "ignored": bool(entry.get("ignored")),
        }

    def all_labels(self) -> Dict[str, Dict[str, object]]:
        labels = self._data.get("labels")
        if isinstance(labels, dict):
            return dict(labels)
        return {}

    def set_pinned(self, label: str, pinned: bool) -> Dict[str, object]:
        return self._update_label(label, lambda entry: entry.__setitem__("pinned", bool(pinned)))

    def set_group(self, label: str, group: str) -> Dict[str, object]:
        clean_group = group.strip()
        if not clean_group:
            def mutator(entry: Dict[str, object]) -> None:
                entry.pop("group", None)
        else:
            def mutator(entry: Dict[str, object]) -> None:
                entry["group"] = clean_group
        return self._update_label(label, mutator)

    def set_ignored(self, label: str, ignored: bool) -> Dict[str, object]:
        return self._update_label(label, lambda entry: entry.__setitem__("ignored", bool(ignored)))

    def _update_label(self, label: str, mutator) -> Dict[str, object]:
        clean_label = label.strip()
        if not clean_label:
            raise ValueError("label is required")
        with self.lock:
            labels = self._data.setdefault("labels", {})
            entry = labels.get(clean_label)
            if not isinstance(entry, dict):
                entry = {}
                labels[clean_label] = entry
            mutator(entry)
            self._cleanup_label(clean_label)
            self._touch_locked()
            self._write_locked()
            return self.label_metadata(clean_label)

    def _cleanup_label(self, label: str) -> None:
        entry = self._data.get("labels", {}).get(label)
        if not isinstance(entry, dict):
            self._data.get("labels", {}).pop(label, None)
            return
        if not entry.get("pinned") and not entry.get("ignored") and not entry.get("group"):
            self._data.get("labels", {}).pop(label, None)

    def _touch_locked(self) -> None:
        self._data["version"] = self.VERSION
        self._data["updated_at"] = int(time.time())

    def _write_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(self.path)


class PhotoPriorityStore:
    """Track per-photo (bucket) priority for photo tagging."""

    VERSION = 1
    DEFAULT_PRIORITY = "normal"
    VALID_PRIORITIES = {"low", "normal", "high"}

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()
        self._data = {
            "version": self.VERSION,
            "updated_at": int(time.time()),
            "priorities": {},
        }
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        priorities = payload.get("priorities")
        if isinstance(priorities, dict):
            cleaned = {}
            for bucket, value in priorities.items():
                if not isinstance(bucket, str):
                    continue
                if isinstance(value, str) and value.lower() in self.VALID_PRIORITIES and bucket.strip():
                    cleaned[bucket.strip()] = value.lower()
            self._data["priorities"] = cleaned
        version = payload.get("version")
        if isinstance(version, int) and version > 0:
            self._data["version"] = version
        updated = payload.get("updated_at")
        if isinstance(updated, (int, float)):
            self._data["updated_at"] = int(updated)

    def get_priority(self, bucket_prefix: str) -> str:
        if not bucket_prefix:
            return self.DEFAULT_PRIORITY
        entry = self._data.get("priorities") or {}
        value = entry.get(bucket_prefix)
        if isinstance(value, str) and value in self.VALID_PRIORITIES:
            return value
        return self.DEFAULT_PRIORITY

    def set_priority(self, bucket_prefix: str, priority: str) -> str:
        clean_bucket = (bucket_prefix or "").strip()
        if not clean_bucket:
            raise ValueError("bucket_prefix is required")
        normalized = (priority or "").strip().lower()
        if normalized not in self.VALID_PRIORITIES:
            raise ValueError("priority must be one of: low, normal, high")
        with self.lock:
            priorities = self._data.setdefault("priorities", {})
            if normalized == self.DEFAULT_PRIORITY:
                priorities.pop(clean_bucket, None)
            else:
                priorities[clean_bucket] = normalized
            self._touch_locked()
            self._write_locked()
        return normalized

    def _touch_locked(self) -> None:
        self._data["version"] = self.VERSION
        self._data["updated_at"] = int(time.time())

    def _write_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(self.path)


class PhotoStatusStore:
    """Track per-photo (bucket) status like done."""

    VERSION = 1

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()
        self._data = {
            "version": self.VERSION,
            "updated_at": int(time.time()),
            "photos": {},
        }
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        photos = payload.get("photos")
        if isinstance(photos, dict):
            self._data["photos"] = photos
        version = payload.get("version")
        if isinstance(version, int) and version > 0:
            self._data["version"] = version
        updated = payload.get("updated_at")
        if isinstance(updated, (int, float)):
            self._data["updated_at"] = int(updated)

    def get(self, bucket_prefix: str) -> Dict[str, object]:
        if not bucket_prefix:
            return {}
        entry = self._data.get("photos", {}).get(bucket_prefix)
        if isinstance(entry, dict):
            return dict(entry)
        return {}

    def is_done(self, bucket_prefix: str) -> bool:
        entry = self.get(bucket_prefix)
        return bool(entry.get("done"))

    def set_done(self, bucket_prefix: str, done: bool, done_by: str = "") -> Dict[str, object]:
        clean_bucket = (bucket_prefix or "").strip()
        if not clean_bucket:
            raise ValueError("bucket_prefix is required")
        clean_by = (done_by or "").strip()
        with self.lock:
            photos = self._data.setdefault("photos", {})
            if not done:
                photos.pop(clean_bucket, None)
                self._touch_locked()
                self._write_locked()
                return {"bucket_prefix": clean_bucket, "done": False}
            entry = photos.get(clean_bucket)
            if not isinstance(entry, dict):
                entry = {}
                photos[clean_bucket] = entry
            entry["done"] = True
            entry["done_at"] = datetime.now(timezone.utc).isoformat()
            if clean_by:
                entry["done_by"] = clean_by
            self._touch_locked()
            self._write_locked()
            return {"bucket_prefix": clean_bucket, **entry}

    def done_buckets(self) -> set[str]:
        photos = self._data.get("photos", {})
        if not isinstance(photos, dict):
            return set()
        return {bucket for bucket, entry in photos.items() if isinstance(entry, dict) and entry.get("done")}

    def _touch_locked(self) -> None:
        self._data["version"] = self.VERSION
        self._data["updated_at"] = int(time.time())

    def _write_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(self.path)


class ManualBoxStore:
    """Persist manual face annotation boxes (non-destructive)."""

    VERSION = 1

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()
        self._data = {
            "version": self.VERSION,
            "updated_at": int(time.time()),
            "boxes": {},
        }
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        boxes = payload.get("boxes")
        if isinstance(boxes, dict):
            self._data["boxes"] = boxes
        version = payload.get("version")
        if isinstance(version, int) and version > 0:
            self._data["version"] = version
        updated = payload.get("updated_at")
        if isinstance(updated, (int, float)):
            self._data["updated_at"] = int(updated)

    def list_boxes(self, bucket_prefix: str, side: Optional[str] = None) -> List[Dict[str, object]]:
        clean_bucket = (bucket_prefix or "").strip()
        if not clean_bucket:
            return []
        entries = self._data.get("boxes", {}).get(clean_bucket)
        if not isinstance(entries, list):
            return []
        normalized_side = (side or "").strip().lower()
        results: List[Dict[str, object]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if normalized_side and entry.get("side") != normalized_side:
                continue
            bbox = _normalize_manual_bbox(entry.get("bbox"))
            if not bbox:
                continue
            face_index = entry.get("face_index")
            if isinstance(face_index, (int, float)):
                face_index_value = int(face_index)
            else:
                face_index_value = None
            results.append(
                {
                    "id": entry.get("id"),
                    "side": entry.get("side") or "front",
                    "bbox": bbox,
                    "label": entry.get("label") or "",
                    "face_index": face_index_value,
                    "created_at": entry.get("created_at"),
                    "updated_at": entry.get("updated_at"),
                }
            )
        return results

    def add_box(
        self,
        bucket_prefix: str,
        side: str,
        bbox: Dict[str, float],
        *,
        face_index: Optional[int] = None,
    ) -> Dict[str, object]:
        clean_bucket = (bucket_prefix or "").strip()
        if not clean_bucket:
            raise ValueError("bucket_prefix is required")
        normalized_side = (side or "").strip().lower()
        if normalized_side not in {"front", "back"}:
            raise ValueError("side must be 'front' or 'back'")
        normalized_bbox = _normalize_manual_bbox(bbox)
        if not normalized_bbox:
            raise ValueError("bbox must include left/top/width/height between 0 and 1")
        face_index_value = int(face_index) if isinstance(face_index, (int, float)) else None
        entry = {
            "id": uuid.uuid4().hex,
            "side": normalized_side,
            "bbox": normalized_bbox,
            "label": "",
            "face_index": face_index_value,
            "created_at": int(time.time()),
            "updated_at": int(time.time()),
        }
        with self.lock:
            boxes = self._data.setdefault("boxes", {})
            rows = boxes.get(clean_bucket)
            if not isinstance(rows, list):
                rows = []
                boxes[clean_bucket] = rows
            rows.append(entry)
            self._touch_locked()
            self._write_locked()
        return entry

    def ensure_face_indices(
        self,
        bucket_prefix: str,
        start_index: int,
        used_indices: Optional[set[int]] = None,
    ) -> int:
        clean_bucket = (bucket_prefix or "").strip()
        if not clean_bucket:
            return start_index
        with self.lock:
            boxes = self._data.setdefault("boxes", {})
            rows = boxes.get(clean_bucket)
            if not isinstance(rows, list):
                return start_index
            used = set(used_indices or set())
            for entry in rows:
                if not isinstance(entry, dict):
                    continue
                face_index = entry.get("face_index")
                if isinstance(face_index, (int, float)):
                    used.add(int(face_index))
            base = max(used) + 1 if used else start_index
            next_index = max(start_index, base)
            changed = False
            for entry in rows:
                if not isinstance(entry, dict):
                    continue
                face_index = entry.get("face_index")
                if isinstance(face_index, (int, float)):
                    continue
                while next_index in used:
                    next_index += 1
                entry["face_index"] = next_index
                used.add(next_index)
                next_index += 1
                changed = True
            if changed:
                self._touch_locked()
                self._write_locked()
            return next_index

    def find_by_face_index(self, bucket_prefix: str, face_index: int) -> Optional[Dict[str, object]]:
        clean_bucket = (bucket_prefix or "").strip()
        if not clean_bucket:
            return None
        entries = self._data.get("boxes", {}).get(clean_bucket)
        if not isinstance(entries, list):
            return None
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            stored = entry.get("face_index")
            if isinstance(stored, (int, float)) and int(stored) == face_index:
                return entry
        return None

    def update_label(self, bucket_prefix: str, box_id: str, label: str) -> Optional[Dict[str, object]]:
        clean_bucket = (bucket_prefix or "").strip()
        clean_id = (box_id or "").strip()
        if not clean_bucket or not clean_id:
            raise ValueError("bucket_prefix and box_id are required")
        clean_label = (label or "").strip()
        with self.lock:
            boxes = self._data.setdefault("boxes", {})
            rows = boxes.get(clean_bucket)
            if not isinstance(rows, list):
                return None
            for entry in rows:
                if not isinstance(entry, dict):
                    continue
                if entry.get("id") != clean_id:
                    continue
                entry["label"] = clean_label
                entry["updated_at"] = int(time.time())
                self._touch_locked()
                self._write_locked()
                return {
                    "id": entry.get("id"),
                    "side": entry.get("side") or "front",
                    "bbox": _normalize_manual_bbox(entry.get("bbox")),
                    "label": entry.get("label") or "",
                    "created_at": entry.get("created_at"),
                    "updated_at": entry.get("updated_at"),
                }
        return None

    def remove_box(self, bucket_prefix: str, box_id: str) -> bool:
        clean_bucket = (bucket_prefix or "").strip()
        clean_id = (box_id or "").strip()
        if not clean_bucket or not clean_id:
            raise ValueError("bucket_prefix and box_id are required")
        with self.lock:
            boxes = self._data.setdefault("boxes", {})
            rows = boxes.get(clean_bucket)
            if not isinstance(rows, list):
                return False
            initial = len(rows)
            boxes[clean_bucket] = [entry for entry in rows if entry.get("id") != clean_id]
            if len(boxes[clean_bucket]) == initial:
                return False
            if not boxes[clean_bucket]:
                boxes.pop(clean_bucket, None)
            self._touch_locked()
            self._write_locked()
            return True

    def _touch_locked(self) -> None:
        self._data["version"] = self.VERSION
        self._data["updated_at"] = int(time.time())

    def _write_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(self.path)


def _setup_runtime(
    *,
    min_confidence: float,
    min_similarity: float,
    sources: Optional[List[str]],
) -> Tuple[
    config_mod.AppConfig,
    FaceMatcher,
    QueueState,
    FacePeopleStore,
    PhotoPriorityStore,
    PhotoStatusStore,
    PhotoTransformStore,
    ManualBoxStore,
]:
    cfg = config_mod.load_config()
    conn = db_mod.connect(cfg.db_path)
    typer.echo("Loading face embeddings…")
    records = load_face_records(
        conn,
        buckets_dir=cfg.buckets_dir,
        review_root=cfg.staging_root / "02_WORKING_BUCKETS",
        min_confidence=min_confidence,
        sources=sources,
    )
    if not records:
        typer.echo("No eligible face embeddings found. Run cli.faces first.", err=True)
        raise typer.Exit(code=1)
    ignore_store = FaceIgnoreStore(cfg.config_dir / "face_ignores.csv")
    ignored_ids = set(ignore_store.all().keys())
    filtered_records = [record for record in records if record.face_id not in ignored_ids]
    matcher = FaceMatcher(filtered_records)
    tag_store = FaceTagStore(cfg.config_dir / "face_tags.csv")
    vote_store = FaceVoteStore(cfg.config_dir / "face_votes.csv")
    people_store = FacePeopleStore(cfg.config_dir / "face_people.json")
    photo_priority_store = PhotoPriorityStore(cfg.config_dir / "photo_priority.json")
    photo_status_store = PhotoStatusStore(cfg.config_dir / "face_photos.json")
    photo_transform_store = PhotoTransformStore(cfg.config_dir / "photo_transforms.json")
    manual_box_store = ManualBoxStore(cfg.config_dir / "manual_boxes.json")
    state = QueueState(
        matcher,
        tag_store,
        vote_store,
        ignore_store,
        min_confidence=min_confidence,
        default_min_similarity=min_similarity,
    )
    return (
        cfg,
        matcher,
        state,
        people_store,
        photo_priority_store,
        photo_status_store,
        photo_transform_store,
        manual_box_store,
    )


def _build_and_store_clusters(
    *,
    cfg: config_mod.AppConfig,
    matcher: FaceMatcher,
    state: QueueState,
    photo_status_store: PhotoStatusStore,
    logger: logging.Logger,
    min_faces: int = CLUSTER_DEFAULT_MIN_FACES,
    similarity: float = CLUSTER_DEFAULT_SIMILARITY,
    bits_per_band: int = CLUSTER_DEFAULT_BITS_PER_BAND,
    band_count: int = CLUSTER_DEFAULT_BAND_COUNT,
    max_bucket_size: int = CLUSTER_DEFAULT_MAX_BUCKET,
    force: bool = False,
) -> FaceClusterStore:
    store = FaceClusterStore(cfg.config_dir / CLUSTER_CACHE_FILENAME)
    done_buckets = photo_status_store.done_buckets()
    excluded_face_ids = _cluster_excluded_face_ids(state, matcher, done_buckets)
    candidate_ids = _cluster_candidate_face_ids(matcher, excluded_face_ids)
    signature = _cluster_signature(
        candidate_ids,
        similarity=similarity,
        min_faces=min_faces,
        bits_per_band=bits_per_band,
        band_count=band_count,
        max_bucket_size=max_bucket_size,
    )
    params = {
        "min_faces": min_faces,
        "similarity": similarity,
        "bits_per_band": bits_per_band,
        "band_count": band_count,
        "max_bucket_size": max_bucket_size,
    }
    if not force and store.is_compatible(signature):
        if logger:
            logger.info(
                "Using cached face clusters (%s clusters)", len(store.clusters())
            )
        return store
    builder = FaceClusterBuilder(
        matcher,
        excluded_face_ids=excluded_face_ids,
        similarity_threshold=similarity,
        min_faces=min_faces,
        bits_per_band=bits_per_band,
        band_count=band_count,
        max_bucket_size=max_bucket_size,
        logger=logger,
    )
    result = builder.build()
    store.write(
        result.clusters,
        signature=signature,
        params=params,
        stats=result.stats,
    )
    if logger:
        logger.info("Wrote %s clusters to %s", len(result.clusters), store.path)
    return store


def _cluster_candidate_face_ids(
    matcher: FaceMatcher,
    excluded_face_ids: Set[str],
) -> List[str]:
    candidates = [
        record.face_id
        for record in matcher.records
        if record.face_id not in excluded_face_ids
    ]
    candidates.sort()
    return candidates


def _cluster_excluded_face_ids(
    state: QueueState,
    matcher: FaceMatcher,
    done_buckets: Set[str],
) -> Set[str]:
    excluded = set(state.labeled_ids) | set(state.ignored_ids)
    if done_buckets:
        for record in matcher.records:
            if record.bucket_prefix in done_buckets:
                excluded.add(record.face_id)
    return excluded


def _cluster_signature(
    candidate_face_ids: Sequence[str],
    *,
    similarity: float,
    min_faces: int,
    bits_per_band: int,
    band_count: int,
    max_bucket_size: int,
) -> str:
    digest = hashlib.sha1()
    params = f"{len(candidate_face_ids)}|{similarity:.4f}|{min_faces}|{bits_per_band}|{band_count}|{max_bucket_size}"
    digest.update(params.encode("utf-8"))
    for face_id in candidate_face_ids:
        digest.update(face_id.encode("utf-8"))
        digest.update(b"|")
    return digest.hexdigest()
app = typer.Typer(add_completion=False)


@app.command("clusters")
def build_clusters(
    min_confidence: float = typer.Option(
        0.35,
        "--min-confidence",
        help="Ignore detections below this detector confidence",
    ),
    source: Optional[List[str]] = typer.Option(
        None,
        "--source",
        help="Limit to one or more bucket sources (repeatable)",
    ),
    similarity_threshold: float = typer.Option(
        CLUSTER_DEFAULT_SIMILARITY,
        "--similarity",
        help="Cosine similarity required to link two detections",
    ),
    min_faces: int = typer.Option(
        CLUSTER_DEFAULT_MIN_FACES,
        "--min-faces",
        help="Minimum detections required to keep a cluster",
    ),
    bits_per_band: int = typer.Option(
        CLUSTER_DEFAULT_BITS_PER_BAND,
        "--bits-per-band",
        help="Random projection bits per band for LSH bucketing",
    ),
    band_count: int = typer.Option(
        CLUSTER_DEFAULT_BAND_COUNT,
        "--band-count",
        help="Number of random projection bands for LSH bucketing",
    ),
    max_bucket_size: int = typer.Option(
        CLUSTER_DEFAULT_MAX_BUCKET,
        "--max-bucket-size",
        help="Skip candidate buckets larger than this size",
    ),
    force: bool = typer.Option(
        False,
        "--force/--use-cache",
        help="Rebuild even if current cache signature matches",
    ),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging level"),
) -> None:
    """Precompute unlabeled face clusters for the Clusters UI."""

    if not 0 < similarity_threshold <= 1:
        raise typer.BadParameter("--similarity must be between 0 and 1")
    if min_faces < 2:
        raise typer.BadParameter("--min-faces must be at least 2")
    if bits_per_band <= 0 or bits_per_band > 24:
        raise typer.BadParameter("--bits-per-band must be between 1 and 24")
    if band_count <= 0 or band_count > 32:
        raise typer.BadParameter("--band-count must be between 1 and 32")
    if max_bucket_size < 2:
        raise typer.BadParameter("--max-bucket-size must be at least 2")

    log_mod.setup_logging(log_level)
    logger = logging.getLogger("cli.faces_queue.clusters")
    (
        cfg,
        matcher,
        state,
        _people_store,
        _photo_priority_store,
        photo_status_store,
        _photo_transform_store,
        _manual_box_store,
    ) = _setup_runtime(
        min_confidence=min_confidence,
        min_similarity=0.40,
        sources=source,
    )
    cluster_store = _build_and_store_clusters(
        cfg=cfg,
        matcher=matcher,
        state=state,
        photo_status_store=photo_status_store,
        logger=logger,
        min_faces=min_faces,
        similarity=similarity_threshold,
        bits_per_band=bits_per_band,
        band_count=band_count,
        max_bucket_size=max_bucket_size,
        force=force,
    )
    typer.echo(
        f"Clusters ready ({len(cluster_store.clusters())} groups) -> {cluster_store.path.as_posix()}"
    )


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    min_confidence: float = typer.Option(
        0.35,
        "--min-confidence",
        help="Ignore detections below this detector confidence",
    ),
    min_similarity: float = typer.Option(
        0.40,
        "--min-similarity",
        help="Initial cosine similarity cutoff for suggested matches",
    ),
    source: Optional[List[str]] = typer.Option(
        None,
        "--source",
        help="Limit to one or more bucket sources (repeatable)",
    ),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging level"),
) -> None:
    """Launch the single-face labeling + confirmation UI."""

    if ctx.invoked_subcommand:
        return
    if not 0 <= min_confidence <= 1:
        raise typer.BadParameter("--min-confidence must be between 0 and 1")
    if not 0 <= min_similarity <= 1:
        raise typer.BadParameter("--min-similarity must be between 0 and 1")

    log_mod.setup_logging(log_level)
    logger = logging.getLogger("cli.faces_queue")
    (
        cfg,
        matcher,
        state,
        people_store,
        photo_priority_store,
        photo_status_store,
        photo_transform_store,
        manual_box_store,
    ) = _setup_runtime(
        min_confidence=min_confidence,
        min_similarity=min_similarity,
        sources=source,
    )

    dataset = _build_dataset(state, min_confidence=min_confidence, min_similarity=min_similarity)
    _write_queue_assets(cfg, dataset)

    cluster_store = _build_and_store_clusters(
        cfg=cfg,
        matcher=matcher,
        state=state,
        photo_status_store=photo_status_store,
        logger=logger,
    )

    server = _start_server(
        cfg,
        state,
        people_store=people_store,
        photo_priority_store=photo_priority_store,
        photo_status_store=photo_status_store,
        photo_transform_store=photo_transform_store,
        manual_box_store=manual_box_store,
        cluster_store=cluster_store,
        sources=source,
        logger=logger,
    )
    url = f"http://127.0.0.1:{server.server_address[1]}/views/faces_queue/index.html"
    typer.echo(f"Face queue running at {url}")
    try:
        webbrowser.open(url)
    except Exception as exc:  # pragma: no cover
        logger.debug("Failed to open browser automatically: %s", exc)
    typer.echo("Press Ctrl+C to stop…")
    _wait_forever(server)


class QueueState:
    def __init__(
        self,
        matcher: FaceMatcher,
        tag_store: FaceTagStore,
        vote_store: FaceVoteStore,
        ignore_store: FaceIgnoreStore,
        *,
        min_confidence: float,
        default_min_similarity: float,
    ) -> None:
        self.matcher = matcher
        self.tag_store = tag_store
        self.vote_store = vote_store
        self.ignore_store = ignore_store
        self.min_confidence = min_confidence
        self.default_min_similarity = default_min_similarity

        self.label_faces: Dict[str, set[str]] = {}
        self.labeled_ids = set()
        self.ignored_ids = set(ignore_store.all().keys())
        self.skipped: Dict[str, set[str]] = {}
        self._history: List[Dict[str, object]] = []
        self._history_lock = threading.Lock()
        for tag in tag_store.all().values():
            self.label_faces.setdefault(tag.label, set()).add(tag.face_id)
            self.labeled_ids.add(tag.face_id)

        sorted_records = sorted(
            matcher.records,
            key=lambda record: record.confidence,
            reverse=True,
        )
        self.unlabeled_ids = [
            record.face_id
            for record in sorted_records
            if record.face_id not in self.labeled_ids and record.face_id not in self.ignored_ids
        ]
        self._unlabeled_index = 0

    # bookkeeping helpers

    def add_label(self, label: str, face_id: str) -> None:
        self.label_faces.setdefault(label, set()).add(face_id)
        self.labeled_ids.add(face_id)

    def unlabeled_remaining(self) -> int:
        return max(len(self.unlabeled_ids) - self._unlabeled_index, 0)

    def pending_counts(self) -> Dict[str, int]:
        return self._pending_counts(self.default_min_similarity)

    def next_unlabeled(self) -> Optional[FaceRecord]:
        while self._unlabeled_index < len(self.unlabeled_ids):
            face_id = self.unlabeled_ids[self._unlabeled_index]
            self._unlabeled_index += 1
            if face_id in self.labeled_ids or face_id in self.ignored_ids:
                continue
            record = self.matcher.record_for(face_id)
            if record is None:
                continue
            return record
        return None

    def unlabeled_records(self, limit: int, min_confidence: float) -> List[FaceRecord]:
        results: List[FaceRecord] = []
        if limit <= 0:
            return results
        for face_id in self.unlabeled_ids:
            if len(results) >= limit:
                break
            if face_id in self.labeled_ids or face_id in self.ignored_ids:
                continue
            record = self.matcher.record_for(face_id)
            if record is None:
                continue
            if record.confidence < min_confidence:
                continue
            results.append(record)
        return results

    def unlabeled_photo_groups(self, min_confidence: float) -> Dict[str, Dict[str, object]]:
        groups: Dict[str, Dict[str, object]] = {}
        for face_id in self.unlabeled_ids:
            if face_id in self.labeled_ids or face_id in self.ignored_ids:
                continue
            record = self.matcher.record_for(face_id)
            if record is None or record.confidence < min_confidence:
                continue
            entry = groups.get(record.bucket_prefix)
            if not entry:
                entry = {
                    "bucket_prefix": record.bucket_prefix,
                    "bucket_source": record.bucket_source,
                    "image_url": record.image,
                    "unlabeled_count": 0,
                    "max_confidence": 0.0,
                }
                groups[record.bucket_prefix] = entry
            entry["unlabeled_count"] += 1
            if record.confidence > entry["max_confidence"]:
                entry["max_confidence"] = record.confidence
        return groups

    def unlabeled_photo_groups(self, min_confidence: float) -> Dict[str, Dict[str, object]]:
        groups: Dict[str, Dict[str, object]] = {}
        for face_id in self.unlabeled_ids:
            if face_id in self.labeled_ids or face_id in self.ignored_ids:
                continue
            record = self.matcher.record_for(face_id)
            if record is None or record.confidence < min_confidence:
                continue
            entry = groups.get(record.bucket_prefix)
            if not entry:
                entry = {
                    "bucket_prefix": record.bucket_prefix,
                    "bucket_source": record.bucket_source,
                    "image_url": record.image,
                    "unlabeled_count": 0,
                    "max_confidence": 0.0,
                }
                groups[record.bucket_prefix] = entry
            entry["unlabeled_count"] += 1
            if record.confidence > entry["max_confidence"]:
                entry["max_confidence"] = record.confidence
        return groups

    def records_for_bucket(self, bucket_prefix: str, variant: Optional[str] = None) -> List[FaceRecord]:
        matches: List[FaceRecord] = []
        if not bucket_prefix:
            return matches
        for record in self.matcher.records:
            if record.bucket_prefix != bucket_prefix:
                continue
            if variant and record.variant_role != variant:
                continue
            matches.append(record)
        return matches

    def refresh_records(self, records: Sequence[FaceRecord]) -> None:
        if not records:
            return
        self.matcher = FaceMatcher(records)
        self.label_faces = {}
        self.labeled_ids = set()
        for tag in self.tag_store.all().values():
            self.label_faces.setdefault(tag.label, set()).add(tag.face_id)
            self.labeled_ids.add(tag.face_id)
        self.ignored_ids = set(self.ignore_store.all().keys())
        sorted_records = sorted(self.matcher.records, key=lambda record: record.confidence, reverse=True)
        self.unlabeled_ids = [
            record.face_id
            for record in sorted_records
            if record.face_id not in self.labeled_ids and record.face_id not in self.ignored_ids
        ]
        self._unlabeled_index = min(self._unlabeled_index, len(self.unlabeled_ids))

    def mark_ignored(self, face_id: str, reason: str, note: str = "") -> None:
        if not face_id:
            return
        self.ignored_ids.add(face_id)
        self.ignore_store.add(face_id, reason, note=note)
        self.clear_skip_for_face(None, face_id)

    def skip_face(self, label: str, face_id: str) -> None:
        if not label or not face_id:
            return
        self.skipped.setdefault(label, set()).add(face_id)

    def skipped_for_label(self, label: str) -> set[str]:
        return self.skipped.get(label, set())

    def clear_skip_for_face(self, label: Optional[str], face_id: str) -> None:
        if not face_id:
            return
        if label:
            faces = self.skipped.get(label)
            if faces:
                faces.discard(face_id)
                if not faces:
                    self.skipped.pop(label, None)
        else:
            for faces in self.skipped.values():
                faces.discard(face_id)
            empty = [key for key, faces in self.skipped.items() if not faces]
            for key in empty:
                self.skipped.pop(key, None)

    def unignore_face(self, face_id: str) -> bool:
        face_id = face_id.strip()
        if not face_id or face_id not in self.ignored_ids:
            return False
        removed = self.ignore_store.remove(face_id)
        if not removed:
            return False
        self.ignored_ids.discard(face_id)
        if face_id not in self.unlabeled_ids:
            self.unlabeled_ids.append(face_id)
        return True

    def history_available(self) -> bool:
        with self._history_lock:
            return bool(self._history)

    def push_history(self, entry: Dict[str, object]) -> None:
        if not entry:
            return
        with self._history_lock:
            self._history.append(entry)
            if len(self._history) > 500:
                self._history.pop(0)

    def pop_history(self) -> Optional[Dict[str, str]]:
        with self._history_lock:
            if not self._history:
                return None
            return self._history.pop()

    def remove_label(self, label: str, face_id: str) -> bool:
        if not face_id or not label:
            return False
        faces = self.label_faces.get(label)
        if not faces or face_id not in faces:
            return False
        faces.remove(face_id)
        if not faces:
            self.label_faces.pop(label, None)
        self.labeled_ids.discard(face_id)
        self.tag_store.clear(face_id)
        self.clear_skip_for_face(label, face_id)
        # requeue for future review
        if face_id not in self.unlabeled_ids:
            self.unlabeled_ids.append(face_id)
        return True

    def merge_labels(self, source_label: str, target_label: str) -> int:
        source_label = source_label.strip()
        target_label = target_label.strip()
        if not source_label or not target_label or source_label == target_label:
            return 0
        source_faces = self.label_faces.get(source_label)
        if not source_faces:
            return 0
        dest_faces = self.label_faces.setdefault(target_label, set())
        moved = 0
        for face_id in list(source_faces):
            if face_id in dest_faces:
                continue
            dest_faces.add(face_id)
            moved += 1
        self.label_faces.pop(source_label, None)
        return moved

    def label_records(self, label: str) -> List[FaceRecord]:
        records: List[FaceRecord] = []
        faces = self.label_faces.get(label, set())
        for face_id in faces:
            record = self.matcher.record_for(face_id)
            if record:
                records.append(record)
        return records

    def labels_payload(self) -> List[Dict[str, object]]:
        payload = [
            {"name": label, "count": len(face_ids)}
            for label, face_ids in sorted(self.label_faces.items(), key=lambda item: item[0].lower())
        ]
        pending_map = self._pending_counts(self.default_min_similarity)
        for entry in payload:
            entry["pending"] = pending_map.get(entry["name"], 0)
        return payload

    def _pending_counts(self, min_similarity: float) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for label, faces in self.label_faces.items():
            if not faces:
                counts[label] = 0
                continue
            rejected = self.vote_store.rejected_for(label)
            skipped = self.skipped_for_label(label)
            excluded = set(self.labeled_ids) | set(self.ignored_ids) | set(skipped)
            candidate = self.matcher.next_candidate(
                faces,
                excluded_ids=excluded,
                rejected_ids=rejected,
                min_similarity=min_similarity,
                min_confidence=self.min_confidence,
            )
            counts[label] = 1 if candidate else 0
        return counts


def _build_dataset(state: QueueState, *, min_confidence: float, min_similarity: float) -> Dict[str, object]:
    labels = state.labels_payload()
    return {
        "generated_at": time.time(),
        "min_confidence": min_confidence,
        "default_similarity": min_similarity,
        "labels": labels,
        "total_faces": state.matcher.count,
        "unlabeled_remaining": state.unlabeled_remaining(),
        "ignored_total": len(state.ignored_ids),
        "history_available": state.history_available(),
    }


def _write_queue_assets(cfg: config_mod.AppConfig, dataset: Dict[str, object]) -> None:
    views_root = cfg.staging_root / "02_WORKING_BUCKETS" / "views"
    queue_dir = views_root / "faces_queue"
    queue_dir.mkdir(parents=True, exist_ok=True)
    templates_dir = cfg.repo_root / "templates" / "faces_queue"
    for filename in ("index.html", "styles.css", "queue_app.js"):
        src = templates_dir / filename
        dst = queue_dir / filename
        dst.write_bytes(src.read_bytes())
    payload_path = queue_dir / "queue_data.js"
    payload_path.write_text(f"window.FACE_QUEUE_DATA = {json.dumps(dataset, ensure_ascii=False)};\n", encoding="utf-8")


def _start_server(
    cfg: config_mod.AppConfig,
    state: QueueState,
    *,
    people_store: FacePeopleStore,
    photo_priority_store: PhotoPriorityStore,
    photo_status_store: PhotoStatusStore,
    photo_transform_store: PhotoTransformStore,
    manual_box_store: ManualBoxStore,
    cluster_store: FaceClusterStore,
    sources: Optional[List[str]],
    logger: logging.Logger,
) -> ThreadingHTTPServer:
    base_dir = cfg.staging_root / "02_WORKING_BUCKETS"
    handler_cls = partial(
        FaceQueueRequestHandler,
        directory=str(base_dir),
        state=state,
        people_store=people_store,
        photo_priority_store=photo_priority_store,
        photo_status_store=photo_status_store,
        photo_transform_store=photo_transform_store,
        manual_box_store=manual_box_store,
        cluster_store=cluster_store,
        cfg=cfg,
        sources=sources,
        logger=logger,
    )
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


class FaceQueueRequestHandler(SimpleHTTPRequestHandler):
    def __init__(
        self,
        *args,
        directory: str,
        state: QueueState,
        people_store: FacePeopleStore,
        photo_priority_store: PhotoPriorityStore,
        photo_status_store: PhotoStatusStore,
        photo_transform_store: PhotoTransformStore,
        manual_box_store: ManualBoxStore,
        cluster_store: FaceClusterStore,
        cfg: config_mod.AppConfig,
        sources: Optional[List[str]],
        logger: logging.Logger,
        **kwargs,
    ) -> None:
        self.state = state
        self.people_store = people_store
        self.photo_priority_store = photo_priority_store
        self.photo_status_store = photo_status_store
        self.photo_transform_store = photo_transform_store
        self.manual_box_store = manual_box_store
        self.cluster_store = cluster_store
        self.cfg = cfg
        self.sources = sources
        self.logger = logger
        super().__init__(*args, directory=directory, **kwargs)

    def do_GET(self) -> None:  # pragma: no cover - manual
        parsed = urlparse(self.path)
        if parsed.path == "/api/people":
            self._serve_people(parsed)
            return
        if parsed.path == "/api/unlabeled":
            self._serve_unlabeled(parsed)
            return
        if parsed.path == "/api/photos":
            self._serve_unlabeled_photos(parsed)
            return
        if parsed.path == "/api/photos":
            self._serve_unlabeled_photos(parsed)
            return
        if parsed.path.startswith("/api/photo/") and parsed.path.endswith("/faces"):
            self._serve_photo_faces(parsed)
            return
        if parsed.path.startswith("/api/face/") and parsed.path.endswith("/context"):
            self._serve_face_context(parsed)
            return
        if parsed.path == "/api/labels":
            self._serve_labels()
            return
        if parsed.path == "/api/labels/detail":
            self._serve_label_detail(parsed)
            return
        if parsed.path == "/api/label/photos":
            self._serve_label_photos(parsed)
            return
        if parsed.path == "/api/photo/transform":
            self._serve_photo_transform(parsed)
            return
        if parsed.path == "/api/photo/manual_boxes":
            self._serve_manual_boxes(parsed)
            return
        if parsed.path == "/api/clusters":
            self._serve_clusters(parsed)
            return
        if parsed.path.startswith("/api/cluster/"):
            self._serve_cluster_detail(parsed)
            return
        if parsed.path == "/api/queue/next":
            self._serve_next_candidate(parsed)
            return
        if parsed.path == "/api/queue/seed":
            self._serve_seed_candidate()
            return
        super().do_GET()

    def do_POST(self) -> None:  # pragma: no cover - manual
        endpoint = self.path.rstrip("/")
        if endpoint == "/api/people/pin":
            self._handle_people_pin()
            return
        if endpoint == "/api/people/group":
            self._handle_people_group()
            return
        if endpoint == "/api/people/ignore":
            self._handle_people_ignore()
            return
        if endpoint == "/api/queue/accept":
            self._handle_accept()
            return
        if endpoint == "/api/queue/reject":
            self._handle_reject()
            return
        if endpoint == "/api/queue/ignore":
            self._handle_ignore()
            return
        if endpoint == "/api/queue/crowd":
            self._handle_crowd_ignore()
            return
        if endpoint == "/api/queue/skip":
            self._handle_skip()
            return
        if endpoint == "/api/queue/undo":
            self._handle_undo()
            return
        if endpoint == "/api/queue/batch":
            self._handle_batch_request()
            return
        if endpoint == "/api/queue/batch/commit":
            self._handle_batch_commit()
            return
        if endpoint == "/api/labels/remove":
            self._handle_label_remove()
            return
        if endpoint == "/api/labels/merge":
            self._handle_label_merge()
            return
        if endpoint == "/api/queue/seed":
            self._handle_seed_label()
            return
        if endpoint == "/api/photo/priority":
            self._handle_photo_priority()
            return
        if endpoint == "/api/photo/done":
            self._handle_photo_done()
            return
        if endpoint == "/api/photo/transform":
            self._handle_photo_transform()
            return
        if endpoint == "/api/photo/manual_box":
            self._handle_manual_box()
            return
        if endpoint == "/api/photo/redetect":
            self._handle_photo_redetect()
            return
        if endpoint.startswith("/api/cluster/") and endpoint.endswith("/label"):
            self._handle_cluster_label(endpoint)
            return
        self.send_error(404, "Unknown endpoint")

    def log_message(self, format: str, *args) -> None:  # pragma: no cover
        if self.logger:
            self.logger.debug("Server: " + format, *args)

    # Helpers

    def _done_bucket_prefixes(self) -> set[str]:
        return self.photo_status_store.done_buckets()

    def _done_face_ids(self) -> set[str]:
        done_buckets = self._done_bucket_prefixes()
        if not done_buckets:
            return set()
        return {record.face_id for record in self.state.matcher.records if record.bucket_prefix in done_buckets}

    def _handle_people_pin(self) -> None:
        payload = self._read_payload()
        label = (payload.get("label") or "").strip()
        if not label:
            self.send_error(400, "label is required")
            return
        pinned = self._coerce_bool(payload.get("pinned"), default=True)
        try:
            metadata = self.people_store.set_pinned(label, pinned)
        except ValueError as exc:
            self.send_error(400, str(exc))
            return
        self._write_json({"status": "ok", "label": label, "metadata": metadata})

    def _handle_people_group(self) -> None:
        payload = self._read_payload()
        label = (payload.get("label") or "").strip()
        if not label:
            self.send_error(400, "label is required")
            return
        group = str(payload.get("group") or "")
        try:
            metadata = self.people_store.set_group(label, group)
        except ValueError as exc:
            self.send_error(400, str(exc))
            return
        self._write_json({"status": "ok", "label": label, "metadata": metadata})

    def _handle_people_ignore(self) -> None:
        payload = self._read_payload()
        label = (payload.get("label") or "").strip()
        if not label:
            self.send_error(400, "label is required")
            return
        ignored = self._coerce_bool(payload.get("ignored"), default=True)
        try:
            metadata = self.people_store.set_ignored(label, ignored)
        except ValueError as exc:
            self.send_error(400, str(exc))
            return
        self._write_json({"status": "ok", "label": label, "metadata": metadata})

    def _handle_photo_priority(self) -> None:
        payload = self._read_payload()
        bucket_prefix = (payload.get("bucket_prefix") or "").strip()
        if not bucket_prefix:
            self.send_error(400, "bucket_prefix is required")
            return
        priority = str(payload.get("priority") or "").strip().lower()
        try:
            value = self.photo_priority_store.set_priority(bucket_prefix, priority)
        except ValueError as exc:
            self.send_error(400, str(exc))
            return
        self._write_json({"status": "ok", "bucket_prefix": bucket_prefix, "priority": value})

    def _handle_photo_done(self) -> None:
        payload = self._read_payload()
        bucket_prefix = (payload.get("bucket_prefix") or "").strip()
        if not bucket_prefix:
            self.send_error(400, "bucket_prefix is required")
            return
        done = self._coerce_bool(payload.get("done"), default=True)
        done_by = str(payload.get("done_by") or "").strip()
        try:
            record = self.photo_status_store.set_done(bucket_prefix, done, done_by=done_by)
        except ValueError as exc:
            self.send_error(400, str(exc))
            return
        self._write_json({"status": "ok", "bucket_prefix": bucket_prefix, "record": record})

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
        payload = self._read_payload()
        bucket_prefix = (payload.get("bucket_prefix") or "").strip()
        side = (payload.get("side") or "").strip().lower()
        if not bucket_prefix:
            self.send_error(400, "bucket_prefix is required")
            return
        if side not in {"front", "back"}:
            self.send_error(400, "side must be 'front' or 'back'")
            return
        rotation = payload.get("rotate")
        try:
            value = self.photo_transform_store.set_rotation(bucket_prefix, side, rotation)
        except ValueError as exc:
            self.send_error(400, str(exc))
            return
        self._write_json({"status": "ok", "bucket_prefix": bucket_prefix, "side": side, "rotate": value})

    def _serve_manual_boxes(self, parsed) -> None:
        params = parse_qs(parsed.query)
        bucket_prefix = (params.get("bucket_prefix") or [""])[0].strip()
        side = (params.get("side") or [""])[0].strip().lower() or None
        if not bucket_prefix:
            self.send_error(400, "bucket_prefix is required")
            return
        self._ensure_manual_face_indices(bucket_prefix)
        boxes = self.manual_box_store.list_boxes(bucket_prefix, side)
        self._write_json({"status": "ok", "bucket_prefix": bucket_prefix, "boxes": boxes})

    def _serve_clusters(self, parsed) -> None:
        params = parse_qs(parsed.query)
        try:
            limit = int((params.get("limit") or ["20"])[0])
        except ValueError:
            limit = 20
        if limit <= 0:
            limit = 20
        try:
            offset = int((params.get("offset") or ["0"])[0])
        except ValueError:
            offset = 0
        if offset < 0:
            offset = 0
        try:
            min_faces = int((params.get("min_faces") or ["3"])[0])
        except ValueError:
            min_faces = 3
        if min_faces < 1:
            min_faces = 1
        clusters = self.cluster_store.clusters() if self.cluster_store else []
        filtered = [
            entry
            for entry in clusters
            if (entry.get("face_count") or 0) >= min_faces
        ]
        filtered.sort(
            key=lambda entry: (
                -(entry.get("face_count") or 0),
                -(entry.get("bucket_count") or 0),
                entry.get("cluster_id") or "",
            )
        )
        total = len(filtered)
        start = min(offset, total)
        end = min(start + limit, total)
        rows = filtered[start:end]
        payload_clusters = []
        for entry in rows:
            payload_clusters.append(
                {
                    "cluster_id": entry.get("cluster_id"),
                    "face_count": entry.get("face_count", 0),
                    "bucket_count": entry.get("bucket_count", 0),
                    "bucket_prefixes": entry.get("bucket_prefixes", []),
                    "member_face_ids": entry.get("member_face_ids", []),
                    "representative": entry.get("representative"),
                    "stats": entry.get("stats", {}),
                }
            )
        metadata = self.cluster_store.metadata() if self.cluster_store else {}
        payload = {
            "status": "ok",
            "clusters": payload_clusters,
            "total": total,
            "offset": start,
            "limit": limit,
            "next_offset": end if end < total else None,
            "has_more": end < total,
            "min_faces": min_faces,
            "metadata": metadata,
        }
        self._write_json(payload)

    def _serve_cluster_detail(self, parsed) -> None:
        parts = parsed.path.strip("/").split("/")
        if len(parts) < 3:
            self.send_error(400, "Missing cluster_id")
            return
        cluster_id = parts[2]
        if not cluster_id:
            self.send_error(400, "Missing cluster_id")
            return
        entry = self.cluster_store.get(cluster_id) if self.cluster_store else None
        if not entry:
            self.send_error(404, "Unknown cluster_id")
            return
        tags = self.state.tag_store.all()
        votes = self.state.vote_store.all()
        ignores = self.state.ignore_store.all()
        faces = []
        for face_id in entry.get("member_face_ids", []):
            face_payload = self._payload_for_face(face_id)
            if not face_payload:
                continue
            face_payload["state"] = self._assignment_for_face(
                face_id, tags=tags, votes=votes, ignores=ignores
            )
            faces.append(face_payload)
        metadata = self.cluster_store.metadata() if self.cluster_store else {}
        payload = {
            "status": "ok",
            "cluster_id": cluster_id,
            "face_count": entry.get("face_count", len(faces)),
            "bucket_count": entry.get("bucket_count", 0),
            "bucket_prefixes": entry.get("bucket_prefixes", []),
            "member_face_ids": entry.get("member_face_ids", []),
            "representative": entry.get("representative"),
            "stats": entry.get("stats", {}),
            "faces": faces,
            "metadata": metadata,
        }
        self._write_json(payload)

    def _handle_manual_box(self) -> None:
        payload = self._read_payload()
        bucket_prefix = (payload.get("bucket_prefix") or "").strip()
        if not bucket_prefix:
            self.send_error(400, "bucket_prefix is required")
            return
        if payload.get("delete"):
            box_id = (payload.get("box_id") or "").strip()
            if not box_id:
                self.send_error(400, "box_id is required")
                return
            try:
                removed = self.manual_box_store.remove_box(bucket_prefix, box_id)
            except ValueError as exc:
                self.send_error(400, str(exc))
                return
            if not removed:
                self.send_error(404, "manual box not found")
                return
            boxes = self.manual_box_store.list_boxes(bucket_prefix, None)
            self._write_json({"status": "ok", "bucket_prefix": bucket_prefix, "boxes": boxes})
            return
        if "bbox" in payload:
            side = (payload.get("side") or "front").strip().lower()
            try:
                next_index = self._ensure_manual_face_indices(bucket_prefix)
                box = self.manual_box_store.add_box(
                    bucket_prefix,
                    side,
                    payload.get("bbox") or {},
                    face_index=next_index,
                )
            except ValueError as exc:
                self.send_error(400, str(exc))
                return
            self._write_json({"status": "ok", "bucket_prefix": bucket_prefix, "box": box})
            return
        if "label" in payload or "box_id" in payload:
            box_id = (payload.get("box_id") or "").strip()
            label = (payload.get("label") or "").strip()
            if not box_id:
                self.send_error(400, "box_id is required")
                return
            try:
                updated = self.manual_box_store.update_label(bucket_prefix, box_id, label)
            except ValueError as exc:
                self.send_error(400, str(exc))
                return
            if not updated:
                self.send_error(404, "manual box not found")
                return
            self._write_json({"status": "ok", "bucket_prefix": bucket_prefix, "box": updated})
            return
        self.send_error(400, "Unsupported manual box payload")

    def _handle_photo_redetect(self) -> None:
        payload = self._read_payload()
        bucket_prefix = (payload.get("bucket_prefix") or "").strip()
        if not bucket_prefix:
            self.send_error(400, "bucket_prefix is required")
            return
        variant = (payload.get("variant") or "raw_front").strip() or "raw_front"
        min_confidence = _coerce_float(payload.get("min_confidence"), default=self.state.min_confidence)
        merge_iou = _coerce_float(payload.get("merge_iou"), default=0.6)
        try:
            response = self._redetect_photo_faces(bucket_prefix, variant, min_confidence, merge_iou)
        except ValueError as exc:
            self.send_error(400, str(exc))
            return
        except FileNotFoundError as exc:
            self.send_error(404, str(exc))
            return
        except RuntimeError as exc:
            self.send_error(500, str(exc))
            return
        self._write_json(response)

    def _handle_cluster_label(self, endpoint: str) -> None:
        parts = endpoint.strip("/").split("/")
        if len(parts) != 4 or parts[0] != "api" or parts[1] != "cluster" or parts[3] != "label":
            self.send_error(404, "Unknown cluster endpoint")
            return
        cluster_id = parts[2]
        entry = self.cluster_store.get(cluster_id) if self.cluster_store else None
        if not entry:
            self.send_error(404, "Unknown cluster_id")
            return
        payload = self._read_payload()
        label = (payload.get("label") or "").strip()
        if not label:
            self.send_error(400, "label is required")
            return
        accepted: List[str] = []
        skipped: List[str] = []
        for face_id in entry.get("member_face_ids", []):
            if face_id in self.state.labeled_ids:
                skipped.append(face_id)
                continue
            record = self.state.matcher.record_for(face_id)
            if record is None:
                continue
            tag = self.state.tag_store.update(
                face_id=face_id,
                bucket_prefix=record.bucket_prefix,
                face_index=record.face_index,
                label=label,
            )
            self.state.add_label(label, face_id)
            self.state.clear_skip_for_face(label, face_id)
            self.state.vote_store.record(face_id, label, "accept", note="cluster")
            accepted.append(tag.face_id)
        if accepted:
            self.state.push_history({"action": "cluster_label", "face_ids": accepted, "label": label})
        payload = {
            "status": "ok",
            "cluster_id": cluster_id,
            "label": label,
            "accepted": accepted,
            "already_labeled": skipped,
            "labels": self.state.labels_payload(),
            "unlabeled_remaining": self.state.unlabeled_remaining(),
            "ignored_total": len(self.state.ignored_ids),
            "history_available": self.state.history_available(),
        }
        self._write_json(payload)

    def _serve_people(self, parsed) -> None:
        params = parse_qs(parsed.query)
        query = (params.get("query") or [""])[0].strip().lower()
        try:
            limit = int((params.get("limit") or ["0"])[0])
        except ValueError:
            limit = 0
        metadata = self.people_store.all_labels()
        label_names = set(self.state.label_faces.keys()) | set(metadata.keys())
        tags = self.state.tag_store.all()
        last_seen: Dict[str, str] = {}
        for tag in tags.values():
            label = (tag.label or "").strip()
            if not label:
                continue
            ts = (tag.updated_at_utc or "").strip()
            if not ts:
                continue
            previous = last_seen.get(label)
            if not previous or ts > previous:
                last_seen[label] = ts
        pending = self.state.pending_counts()
        people: List[Dict[str, object]] = []
        for label in sorted(label_names, key=lambda value: value.lower()):
            clean_label = label.strip()
            if not clean_label:
                continue
            meta = self.people_store.label_metadata(clean_label)
            entry = {
                "label": clean_label,
                "face_count": len(self.state.label_faces.get(clean_label, set())),
                "pending_count": pending.get(clean_label, 0),
                "last_seen": last_seen.get(clean_label, ""),
                "pinned": meta["pinned"],
                "group": meta["group"],
                "ignored": meta["ignored"],
            }
            if query:
                haystack = f"{clean_label} {entry['group']}".lower()
                if query not in haystack:
                    continue
            people.append(entry)
        total = len(people)
        if limit > 0:
            people = people[:limit]
        self._write_json({"status": "ok", "people": people, "total": total})

    def _serve_unlabeled(self, parsed) -> None:
        params = parse_qs(parsed.query)
        try:
            limit = int((params.get("limit") or ["200"])[0])
        except ValueError:
            limit = 200
        if limit <= 0:
            limit = 200
        try:
            min_confidence = float((params.get("min_confidence") or [str(self.state.min_confidence)])[0])
        except ValueError:
            min_confidence = self.state.min_confidence
        records = self.state.unlabeled_records(limit, min_confidence)
        done_buckets = self._done_bucket_prefixes()
        if done_buckets:
            records = [record for record in records if record.bucket_prefix not in done_buckets]
        items = [_record_payload(record) for record in records]
        payload = {
            "status": "ok",
            "items": items,
            "count": len(items),
            "remaining_estimate": self.state.unlabeled_remaining(),
        }
        self._write_json(payload)

    def _serve_unlabeled_photos(self, parsed) -> None:
        params = parse_qs(parsed.query)
        try:
            limit = int((params.get("limit") or ["60"])[0])
        except ValueError:
            limit = 60
        if limit <= 0:
            limit = 60
        try:
            min_confidence = float((params.get("min_confidence") or [str(self.state.min_confidence)])[0])
        except ValueError:
            min_confidence = self.state.min_confidence
        try:
            cursor = int((params.get("cursor") or ["0"])[0])
        except ValueError:
            cursor = 0
        if cursor < 0:
            cursor = 0
        mode = (params.get("mode") or [""])[0].strip().lower()
        priority_filter = (params.get("priority") or ["all"])[0].strip().lower()
        if priority_filter not in {"all", "high", "normal", "low"}:
            priority_filter = "all"
        include_done = self._coerce_bool((params.get("include_done") or ["0"])[0], default=False)
        only_done = self._coerce_bool((params.get("only_done") or ["0"])[0], default=False)
        tags = self.state.tag_store.all()
        labeled_counts: Dict[str, int] = {}
        for tag in tags.values():
            bucket = (tag.bucket_prefix or "").strip()
            if not bucket:
                continue
            labeled_counts[bucket] = labeled_counts.get(bucket, 0) + 1
        groups = self.state.unlabeled_photo_groups(min_confidence)
        bucket_meta: Dict[str, Dict[str, object]] = {}
        for record in self.state.matcher.records:
            bucket = record.bucket_prefix
            entry = bucket_meta.get(bucket)
            if not entry:
                bucket_meta[bucket] = {
                    "bucket_prefix": bucket,
                    "bucket_source": record.bucket_source,
                    "image_url": record.image,
                    "max_confidence": record.confidence,
                }
                continue
            if record.confidence > (entry.get("max_confidence") or 0.0):
                entry["max_confidence"] = record.confidence
        rows = []
        if mode == "review":
            for bucket_prefix, labeled_count in labeled_counts.items():
                if labeled_count <= 0:
                    continue
                base = groups.get(bucket_prefix) or bucket_meta.get(bucket_prefix)
                if not base:
                    continue
                entry = dict(base)
                entry.setdefault("bucket_prefix", bucket_prefix)
                entry.setdefault("bucket_source", base.get("bucket_source"))
                entry.setdefault("image_url", base.get("image_url"))
                entry["unlabeled_count"] = (groups.get(bucket_prefix) or {}).get("unlabeled_count", 0)
                entry["max_confidence"] = (groups.get(bucket_prefix) or {}).get(
                    "max_confidence",
                    base.get("max_confidence") or 0.0,
                )
                entry["labeled_count"] = labeled_count
                status = self.photo_status_store.get(bucket_prefix)
                done = bool(status.get("done"))
                if only_done and not done:
                    continue
                if done and not include_done and not only_done:
                    continue
                entry["done"] = done
                if status.get("done_at"):
                    entry["done_at"] = status.get("done_at")
                entry["priority"] = self.photo_priority_store.get_priority(bucket_prefix)
                front_url = self._bucket_asset_url(bucket_prefix, "web_front.jpg")
                entry["has_front"] = bool(front_url)
                if front_url:
                    entry["front_url"] = front_url
                back_url = self._bucket_asset_url(bucket_prefix, "web_back.jpg")
                entry["has_back"] = bool(back_url)
                if back_url:
                    entry["back_url"] = back_url
                rows.append(entry)
        else:
            for entry in groups.values():
                bucket_prefix = entry.get("bucket_prefix") or ""
                status = self.photo_status_store.get(bucket_prefix)
                done = bool(status.get("done"))
                if only_done and not done:
                    continue
                if done and not include_done and not only_done:
                    continue
                entry["done"] = done
                if status.get("done_at"):
                    entry["done_at"] = status.get("done_at")
                entry["priority"] = self.photo_priority_store.get_priority(bucket_prefix)
                entry["labeled_count"] = labeled_counts.get(bucket_prefix, 0)
                front_url = self._bucket_asset_url(bucket_prefix, "web_front.jpg")
                entry["has_front"] = bool(front_url)
                if front_url:
                    entry["front_url"] = front_url
                back_url = self._bucket_asset_url(bucket_prefix, "web_back.jpg")
                entry["has_back"] = bool(back_url)
                if back_url:
                    entry["back_url"] = back_url
                rows.append(entry)
        priority_rank = {"high": 0, "normal": 1, "low": 2}
        rows.sort(
            key=lambda entry: (
                priority_rank.get(entry.get("priority") or "normal", 1),
                -(entry.get("unlabeled_count") or 0),
                -(entry.get("labeled_count") or 0),
                -(entry.get("max_confidence") or 0.0),
                entry.get("bucket_prefix") or "",
            )
        )
        if priority_filter != "all":
            rows = [entry for entry in rows if entry.get("priority") == priority_filter]
        total_rows = len(rows)
        start = min(cursor, total_rows)
        end = min(start + limit, total_rows)
        sliced = rows[start:end]
        has_more = end < total_rows
        next_cursor = end if has_more else None
        payload = {
            "status": "ok",
            "photos": sliced,
            "total_photos": total_rows,
            "remaining_estimate": self.state.unlabeled_remaining(),
            "cursor": start,
            "next_cursor": next_cursor,
            "has_more": has_more,
            "priority_filter": priority_filter,
        }
        self._write_json(payload)

    def _serve_photo_faces(self, parsed) -> None:
        parts = parsed.path.strip("/").split("/")
        if len(parts) < 4:
            self.send_error(400, "Missing bucket prefix")
            return
        bucket_prefix = parts[2]
        params = parse_qs(parsed.query)
        variant = (params.get("variant") or [""])[0].strip() or None
        payload = self._photo_faces_payload(bucket_prefix, variant)
        if not payload:
            self._write_json({"status": "error", "message": "No faces found for that bucket"}, status=404)
            return
        self._write_json(payload)

    def _photo_faces_payload(self, bucket_prefix: str, variant: Optional[str]) -> Optional[Dict[str, object]]:
        records = self.state.records_for_bucket(bucket_prefix, variant)
        if not records:
            return None
        tags = self.state.tag_store.all()
        votes = self.state.vote_store.all()
        ignores = self.state.ignore_store.all()
        faces = []
        for record in records:
            faces.append(
                {
                    "face_id": record.face_id,
                    "variant": record.variant_role,
                    "confidence": record.confidence,
                    "bbox": {
                        "left": record.bbox[0],
                        "top": record.bbox[1],
                        "width": record.bbox[2],
                        "height": record.bbox[3],
                    },
                    "state": self._assignment_for_face(record.face_id, tags=tags, votes=votes, ignores=ignores),
                }
            )
        self._ensure_manual_face_indices(bucket_prefix)
        manual_boxes = self.manual_box_store.list_boxes(bucket_prefix, "front")
        for box in manual_boxes:
            face_index = box.get("face_index")
            if face_index is None:
                continue
            face_id = f"{bucket_prefix}:{face_index}"
            faces.append(
                {
                    "face_id": face_id,
                    "variant": "manual",
                    "confidence": 1.0,
                    "bbox": box.get("bbox"),
                    "is_manual": True,
                    "state": self._assignment_for_face(face_id, tags=tags, votes=votes, ignores=ignores),
                }
            )
        front_url = self._bucket_asset_url(bucket_prefix, "web_front.jpg")
        back_url = self._bucket_asset_url(bucket_prefix, "web_back.jpg")
        payload = {
            "status": "ok",
            "bucket_prefix": bucket_prefix,
            "variant": variant or records[0].variant_role,
            "image_url": records[0].image,
            "front_url": front_url,
            "has_front": bool(front_url),
            "has_back": bool(back_url),
            "back_url": back_url,
            "faces": faces,
        }
        if self.photo_transform_store:
            transform = self.photo_transform_store.get_transform(bucket_prefix)
            payload.update(transform)
        return payload

    def _serve_face_context(self, parsed) -> None:
        parts = parsed.path.strip("/").split("/")
        if len(parts) < 4:
            self.send_error(400, "Missing face_id")
            return
        face_id = parts[2]
        record = self.state.matcher.record_for(face_id)
        if record is None:
            self.send_error(404, "Unknown face_id")
            return
        tags = self.state.tag_store.all()
        votes = self.state.vote_store.all()
        ignores = self.state.ignore_store.all()
        assignment = self._assignment_for_face(face_id, tags=tags, votes=votes, ignores=ignores)
        faces = []
        target_index = 0
        for idx, rec in enumerate(self.state.records_for_bucket(record.bucket_prefix)):
            face_payload = _record_payload(rec)
            face_payload["state"] = self._assignment_for_face(rec.face_id, tags=tags, votes=votes, ignores=ignores)
            faces.append(face_payload)
            if rec.face_id == face_id:
                target_index = idx
        payload = {
            "status": "ok",
            "face": _record_payload(record),
            "assignment": assignment,
            "bucket_prefix": record.bucket_prefix,
            "image_url": record.image,
            "faces": faces,
            "target_index": target_index,
        }
        self._write_json(payload)

    def _assignment_for_face(self, face_id: str, *, tags, votes, ignores) -> Dict[str, Optional[object]]:
        tag = tags.get(face_id)
        label = tag.label if tag else None
        verdict = None
        if label:
            vote = votes.get((face_id, label))
            if vote:
                verdict = vote.verdict
        ignored = face_id in self.state.ignored_ids
        ignore_reason = None
        if ignored:
            ignore_entry = ignores.get(face_id)
            if ignore_entry:
                ignore_reason = ignore_entry.reason
        return {
            "label": label,
            "vote": verdict,
            "ignored": ignored,
            "ignore_reason": ignore_reason,
        }

    def _serve_labels(self) -> None:
        payload = {
            "status": "ok",
            "labels": self.state.labels_payload(),
            "total_faces": self.state.matcher.count,
            "unlabeled_remaining": self.state.unlabeled_remaining(),
            "ignored_total": len(self.state.ignored_ids),
            "history_available": self.state.history_available(),
        }
        self._write_json(payload)

    def _serve_label_detail(self, parsed) -> None:
        params = parse_qs(parsed.query)
        label = (params.get("label") or [""])[0].strip()
        if not label:
            self.send_error(400, "label is required")
            return
        records = self.state.label_records(label)
        tags = self.state.tag_store.all()
        faces = []
        for record in records:
            entry = _record_payload(record)
            tag = tags.get(record.face_id)
            if tag:
                entry["updated_at"] = tag.updated_at_utc
                entry["note"] = tag.note
            faces.append(entry)
        faces.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
        self._write_json({"status": "ok", "label": label, "faces": faces})

    def _serve_label_photos(self, parsed) -> None:
        params = parse_qs(parsed.query)
        label = (params.get("label") or [""])[0].strip()
        if not label:
            self.send_error(400, "label is required")
            return
        try:
            limit = int((params.get("limit") or ["200"])[0])
        except ValueError:
            limit = 200
        if limit <= 0:
            limit = 200
        try:
            offset = int((params.get("offset") or ["0"])[0])
        except ValueError:
            offset = 0
        if offset < 0:
            offset = 0
        include_done = self._coerce_bool((params.get("include_done") or ["0"])[0], default=False)
        try:
            min_confidence = float((params.get("min_confidence") or [str(self.state.min_confidence)])[0])
        except ValueError:
            min_confidence = self.state.min_confidence

        tags = self.state.tag_store.all()
        label_buckets: set[str] = set()
        labeled_counts: Dict[str, int] = {}
        for tag in tags.values():
            bucket = (tag.bucket_prefix or "").strip()
            if not bucket:
                continue
            labeled_counts[bucket] = labeled_counts.get(bucket, 0) + 1
            if tag.label == label:
                label_buckets.add(bucket)
        if not label_buckets:
            self._write_json(
                {
                    "status": "ok",
                    "label": label,
                    "photos": [],
                    "total_photos": 0,
                    "offset": offset,
                    "limit": limit,
                    "has_more": False,
                    "next_offset": None,
                }
            )
            return
        groups = self.state.unlabeled_photo_groups(min_confidence)
        bucket_meta: Dict[str, Dict[str, object]] = {}
        for record in self.state.matcher.records:
            bucket_prefix = record.bucket_prefix
            if bucket_prefix not in label_buckets:
                continue
            entry = bucket_meta.get(bucket_prefix)
            if not entry:
                bucket_meta[bucket_prefix] = {
                    "bucket_prefix": bucket_prefix,
                    "bucket_source": record.bucket_source,
                    "image_url": record.image,
                    "max_confidence": record.confidence,
                }
                continue
            if record.confidence > (entry.get("max_confidence") or 0.0):
                entry["max_confidence"] = record.confidence

        rows = []
        for bucket_prefix in label_buckets:
            base = groups.get(bucket_prefix) or bucket_meta.get(bucket_prefix)
            if not base:
                continue
            entry = dict(base)
            entry.setdefault("bucket_prefix", bucket_prefix)
            entry.setdefault("bucket_source", base.get("bucket_source"))
            entry.setdefault("image_url", base.get("image_url"))
            entry["unlabeled_count"] = (groups.get(bucket_prefix) or {}).get("unlabeled_count", 0)
            entry["max_confidence"] = (groups.get(bucket_prefix) or {}).get(
                "max_confidence",
                base.get("max_confidence") or 0.0,
            )
            entry["labeled_count"] = labeled_counts.get(bucket_prefix, 0)
            status = self.photo_status_store.get(bucket_prefix)
            done = bool(status.get("done"))
            if done and not include_done:
                continue
            entry["done"] = done
            if status.get("done_at"):
                entry["done_at"] = status.get("done_at")
            entry["priority"] = self.photo_priority_store.get_priority(bucket_prefix)
            front_url = self._bucket_asset_url(bucket_prefix, "web_front.jpg")
            entry["has_front"] = bool(front_url)
            if front_url:
                entry["front_url"] = front_url
            back_url = self._bucket_asset_url(bucket_prefix, "web_back.jpg")
            entry["has_back"] = bool(back_url)
            if back_url:
                entry["back_url"] = back_url
            rows.append(entry)

        priority_rank = {"high": 0, "normal": 1, "low": 2}
        rows.sort(
            key=lambda entry: (
                priority_rank.get(entry.get("priority") or "normal", 1),
                -(entry.get("unlabeled_count") or 0),
                -(entry.get("labeled_count") or 0),
                -(entry.get("max_confidence") or 0.0),
                entry.get("bucket_prefix") or "",
            )
        )
        total_rows = len(rows)
        start = min(offset, total_rows)
        end = min(start + limit, total_rows)
        sliced = rows[start:end]
        has_more = end < total_rows
        next_offset = end if has_more else None
        self._write_json(
            {
                "status": "ok",
                "label": label,
                "photos": sliced,
                "total_photos": total_rows,
                "offset": start,
                "limit": limit,
                "has_more": has_more,
                "next_offset": next_offset,
            }
        )

    def _serve_seed_candidate(self) -> None:
        record = self.state.next_unlabeled()
        done_buckets = self._done_bucket_prefixes()
        while record and record.bucket_prefix in done_buckets:
            record = self.state.next_unlabeled()
        if not record:
            self._write_json({"status": "empty"})
            return
        payload = {"status": "ok", "candidate": _record_payload(record)}
        self._write_json(payload)

    def _handle_seed_label(self) -> None:
        payload = self._read_payload()
        face_id = (payload.get("face_id") or "").strip()
        label = (payload.get("label") or "").strip()
        if not face_id or not label:
            self.send_error(400, "face_id and label are required")
            return
        record = self.state.matcher.record_for(face_id)
        if record is None:
            manual = self._manual_face_record(face_id)
            if not manual:
                self.send_error(404, "Unknown face_id")
                return
            bucket_prefix = manual["bucket_prefix"]
            face_index = manual["face_index"]
        else:
            bucket_prefix = record.bucket_prefix
            face_index = record.face_index
        tag = self.state.tag_store.update(
            face_id=face_id,
            bucket_prefix=bucket_prefix,
            face_index=face_index,
            label=label,
        )
        self.state.add_label(label, face_id)
        self.state.clear_skip_for_face(label, face_id)
        self.state.vote_store.record(face_id, label, "accept")
        self.state.push_history({"action": "seed", "face_id": face_id, "label": label})
        self._write_json({"status": "ok", "tag": {"label": tag.label, "face_id": tag.face_id}})

    def _serve_next_candidate(self, parsed) -> None:
        params = parse_qs(parsed.query)
        label = (params.get("label") or [""])[0].strip()
        if not label:
            self.send_error(400, "label parameter is required")
            return
        try:
            min_similarity = float((params.get("min_similarity") or ["0"])[0])
        except ValueError:
            min_similarity = 0.0

        positives = self.state.label_faces.get(label, set())
        if not positives:
            self.send_error(404, f"No labeled faces stored for '{label}'. Label one via seed mode first.")
            return
        rejected = self.state.vote_store.rejected_for(label)
        skipped = self.state.skipped_for_label(label)
        excluded = set(self.state.labeled_ids) | set(self.state.ignored_ids) | set(skipped) | self._done_face_ids()
        candidate = self.state.matcher.next_candidate(
            positives,
            excluded_ids=excluded,
            rejected_ids=rejected,
            min_similarity=min_similarity,
            min_confidence=self.state.min_confidence,
        )
        if not candidate:
            self._write_json({"status": "empty"})
            return
        record, score = candidate
        payload = {"status": "ok", "candidate": _record_payload(record, similarity=score)}
        self._write_json(payload)

    def _handle_accept(self) -> None:
        payload = self._read_payload()
        face_id = (payload.get("face_id") or "").strip()
        label = (payload.get("label") or "").strip()
        if not face_id or not label:
            self.send_error(400, "face_id and label are required")
            return
        record = self.state.matcher.record_for(face_id)
        if record is None:
            self.send_error(404, "Unknown face_id")
            return
        tag = self.state.tag_store.update(
            face_id=face_id,
            bucket_prefix=record.bucket_prefix,
            face_index=record.face_index,
            label=label,
        )
        self.state.add_label(label, face_id)
        self.state.clear_skip_for_face(label, face_id)
        self.state.vote_store.record(face_id, label, "accept")
        self.state.push_history({"action": "accept", "face_id": face_id, "label": label})
        self._write_json({"status": "ok", "tag": {"label": tag.label, "face_id": tag.face_id}})

    def _handle_reject(self) -> None:
        payload = self._read_payload()
        face_id = (payload.get("face_id") or "").strip()
        label = (payload.get("label") or "").strip()
        note = (payload.get("note") or "").strip()
        if not face_id or not label:
            self.send_error(400, "face_id and label are required")
            return
        self.state.vote_store.record(face_id, label, "reject", note=note)
        self.state.clear_skip_for_face(label, face_id)
        self.state.push_history({"action": "reject", "face_id": face_id, "label": label})
        self._write_json({"status": "ok"})

    def _handle_ignore(self) -> None:
        payload = self._read_payload()
        face_id = (payload.get("face_id") or "").strip()
        reason = (payload.get("reason") or "background").strip() or "background"
        note = (payload.get("note") or "").strip()
        if not face_id:
            self.send_error(400, "face_id is required")
            return
        self.state.mark_ignored(face_id, reason, note=note)
        self.state.push_history({"action": "ignore", "face_id": face_id, "label": ""})
        self._write_json({"status": "ok"})

    def _handle_crowd_ignore(self) -> None:
        payload = self._read_payload()
        bucket_prefix = (payload.get("bucket_prefix") or "").strip()
        reason = (payload.get("reason") or "crowd").strip() or "crowd"
        if not bucket_prefix:
            self.send_error(400, "bucket_prefix is required")
            return
        ignored: List[str] = []
        for record in self.state.matcher.records:
            if record.bucket_prefix != bucket_prefix:
                continue
            face_id = record.face_id
            if face_id in self.state.labeled_ids or face_id in self.state.ignored_ids:
                continue
            self.state.mark_ignored(face_id, reason, note="crowd")
            ignored.append(face_id)
        if ignored:
            self.state.push_history({"action": "crowd", "face_ids": ignored})
        self._write_json(
            {
                "status": "ok",
                "bucket_prefix": bucket_prefix,
                "ignored": len(ignored),
                "labels": self.state.labels_payload(),
                "unlabeled_remaining": self.state.unlabeled_remaining(),
                "ignored_total": len(self.state.ignored_ids),
                "history_available": self.state.history_available(),
            }
        )

    def _handle_skip(self) -> None:
        payload = self._read_payload()
        face_id = (payload.get("face_id") or "").strip()
        label = (payload.get("label") or "").strip()
        if not face_id or not label:
            self.send_error(400, "face_id and label are required")
            return
        self.state.skip_face(label, face_id)
        self._write_json({"status": "ok"})

    def _handle_undo(self) -> None:
        entry = self.state.pop_history()
        if not entry:
            self._write_json({"status": "empty", "history_available": False})
            return
        action = (entry.get("action") or "").strip()
        face_id = (entry.get("face_id") or "").strip()
        label = (entry.get("label") or "").strip()
        restored_face = None
        if action in {"accept", "seed"} and face_id and label:
            removed = self.state.remove_label(label, face_id)
            self.state.vote_store.clear(face_id, label)
            if removed:
                restored_face = self._payload_for_face(face_id)
        elif action == "reject" and face_id and label:
            if self.state.vote_store.clear(face_id, label):
                restored_face = self._payload_for_face(face_id)
        elif action == "ignore" and face_id:
            if self.state.unignore_face(face_id):
                restored_face = self._payload_for_face(face_id)
        elif action == "crowd":
            face_ids = entry.get("face_ids") or []
            restored_ids: List[str] = []
            for raw_id in face_ids:
                candidate_id = str(raw_id).strip()
                if not candidate_id:
                    continue
                if self.state.unignore_face(candidate_id):
                    restored_ids.append(candidate_id)
            if restored_ids:
                restored_face = self._payload_for_face(restored_ids[-1])
        payload = {
            "status": "ok",
            "history_available": self.state.history_available(),
            "labels": self.state.labels_payload(),
            "unlabeled_remaining": self.state.unlabeled_remaining(),
            "ignored_total": len(self.state.ignored_ids),
        }
        if restored_face:
            payload["restored_face"] = restored_face
        self._write_json(payload)

    def _handle_batch_request(self) -> None:
        payload = self._read_payload()
        label = (payload.get("label") or "").strip()
        if not label:
            self.send_error(400, "label is required")
            return
        try:
            limit = int(payload.get("limit") or 12)
        except ValueError:
            limit = 12
        try:
            min_similarity = float(payload.get("min_similarity") or self.state.min_confidence)
        except ValueError:
            min_similarity = self.state.min_confidence
        positives = self.state.label_faces.get(label, set())
        if not positives:
            self.send_error(404, f"No labeled faces stored for '{label}'. Seed this label first.")
            return
        rejected = self.state.vote_store.rejected_for(label)
        skipped = self.state.skipped_for_label(label)
        excluded = set(self.state.labeled_ids) | set(self.state.ignored_ids) | set(skipped) | self._done_face_ids()
        batch = self.state.matcher.ranked_candidates(
            positives,
            excluded_ids=excluded,
            rejected_ids=rejected,
            min_similarity=min_similarity,
            min_confidence=self.state.min_confidence,
            limit=limit,
        )
        candidates = [
            _record_payload(record, similarity=score)
            for record, score in batch
        ]
        self._write_json({"status": "ok", "candidates": candidates})

    def _handle_batch_commit(self) -> None:
        payload = self._read_payload()
        label = (payload.get("label") or "").strip()
        if not label:
            self.send_error(400, "label is required")
            return
        accept_ids = payload.get("accept_ids") or []
        reject_ids = payload.get("reject_ids") or []
        accepted: List[str] = []
        rejected: List[str] = []
        for face_id in accept_ids:
            face_id = str(face_id).strip()
            record = self.state.matcher.record_for(face_id)
            if record is None:
                continue
            tag = self.state.tag_store.update(
                face_id=face_id,
                bucket_prefix=record.bucket_prefix,
                face_index=record.face_index,
                label=label,
            )
            self.state.add_label(label, face_id)
            self.state.vote_store.record(face_id, label, "accept", note="batch")
            self.state.clear_skip_for_face(label, face_id)
            self.state.push_history({"action": "accept", "face_id": face_id, "label": label})
            accepted.append(tag.face_id)
        for face_id in reject_ids:
            face_id = str(face_id).strip()
            if not face_id:
                continue
            self.state.vote_store.record(face_id, label, "reject", note="batch")
            self.state.clear_skip_for_face(label, face_id)
            self.state.push_history({"action": "reject", "face_id": face_id, "label": label})
            rejected.append(face_id)
        self._write_json(
            {
                "status": "ok",
                "accepted": accepted,
                "rejected": rejected,
                "labels": self.state.labels_payload(),
                "unlabeled_remaining": self.state.unlabeled_remaining(),
                "ignored_total": len(self.state.ignored_ids),
                "history_available": self.state.history_available(),
            }
        )

    def _handle_label_remove(self) -> None:
        payload = self._read_payload()
        label = (payload.get("label") or "").strip()
        face_id = (payload.get("face_id") or "").strip()
        if not label or not face_id:
            self.send_error(400, "label and face_id are required")
            return
        removed = self.state.remove_label(label, face_id)
        if not removed:
            self.send_error(404, "Face not found for this label")
            return
        self.state.vote_store.record(face_id, label, "reject", note="removed")
        self._write_json(
            {
                "status": "ok",
                "labels": self.state.labels_payload(),
                "unlabeled_remaining": self.state.unlabeled_remaining(),
                "ignored_total": len(self.state.ignored_ids),
                "history_available": self.state.history_available(),
            }
        )

    def _handle_label_merge(self) -> None:
        payload = self._read_payload()
        source_label = (payload.get("source_label") or "").strip()
        target_label = (payload.get("target_label") or "").strip()
        if not source_label or not target_label:
            self.send_error(400, "source_label and target_label are required")
            return
        if source_label == target_label:
            self.send_error(400, "Choose two different labels to merge")
            return
        if not self.state.label_faces.get(source_label):
            self.send_error(404, f"Unknown label '{source_label}'")
            return
        moved = self.state.merge_labels(source_label, target_label)
        tags_updated = self.state.tag_store.merge_labels(source_label, target_label)
        votes_updated = self.state.vote_store.merge_labels(source_label, target_label)
        payload = {
            "status": "ok",
            "source_label": source_label,
            "target_label": target_label,
            "moved": moved,
            "tags_updated": tags_updated,
            "votes_updated": votes_updated,
            "labels": self.state.labels_payload(),
            "unlabeled_remaining": self.state.unlabeled_remaining(),
            "ignored_total": len(self.state.ignored_ids),
            "history_available": self.state.history_available(),
        }
        self._write_json(payload)

    def _payload_for_face(self, face_id: str) -> Optional[Dict[str, object]]:
        if not face_id:
            return None
        record = self.state.matcher.record_for(face_id)
        if record is None:
            return None
        return _record_payload(record)

    def _ensure_manual_face_indices(self, bucket_prefix: str) -> int:
        used = {
            record.face_index
            for record in self.state.matcher.records
            if record.bucket_prefix == bucket_prefix
        }
        start_index = max(used) + 1 if used else 0
        return self.manual_box_store.ensure_face_indices(bucket_prefix, start_index, used_indices=used)

    def _manual_face_record(self, face_id: str) -> Optional[Dict[str, object]]:
        if not face_id:
            return None
        if ":" not in face_id:
            return None
        bucket_prefix, raw_index = face_id.split(":", 1)
        try:
            face_index = int(raw_index)
        except ValueError:
            return None
        self._ensure_manual_face_indices(bucket_prefix)
        entry = self.manual_box_store.find_by_face_index(bucket_prefix, face_index)
        if not entry:
            return None
        return {
            "bucket_prefix": bucket_prefix,
            "face_index": face_index,
        }

    def _redetect_photo_faces(
        self,
        bucket_prefix: str,
        variant: str,
        min_confidence: float,
        merge_iou: float,
    ) -> Dict[str, object]:
        conn = db_mod.connect(self.cfg.db_path)
        try:
            bucket_id = self._bucket_id_for_prefix(conn, bucket_prefix)
            if not bucket_id:
                raise ValueError("Unknown bucket_prefix")
            sidecar = self._load_sidecar(bucket_prefix)
            variant_role, variant_info = self._select_variant(sidecar, variant)
            if not variant_info:
                raise ValueError("Requested variant not found")
            image_path = Path(str(variant_info.get("path") or ""))
            if not image_path.exists():
                raise FileNotFoundError("Image file missing for requested variant")
            file_sha = variant_info.get("sha256") or variant_info.get("file_sha256")
            if not file_sha:
                raise ValueError("Missing sha256 for requested variant")
            orientation_info = orientation_mod.extract_orientation_info(sidecar)
            image_data = _load_oriented_bgr(image_path, orientation_info)
            models_root = self.cfg.staging_root / "03_MODELS" / "faces"
            recognizer = FaceRecognizer(models_root, logger=self.logger)
            detections = recognizer.process_image(
                image_path,
                min_score=min_confidence,
                max_faces=50,
                max_dimension=3600,
                image_data=image_data,
            )
            existing = self._load_existing_bboxes(conn, bucket_id, variant_role)
            new_faces = [
                detection
                for detection in detections
                if not any(_bbox_iou(detection.bbox, existing_box) >= merge_iou for existing_box in existing)
            ]
            added = self._insert_face_detections(conn, bucket_id, variant_role, file_sha, new_faces)
            if added:
                self._refresh_face_records(conn)
            payload = self._photo_faces_payload(bucket_prefix, variant_role)
            if not payload:
                payload = {
                    "status": "ok",
                    "bucket_prefix": bucket_prefix,
                    "variant": variant_role,
                    "image_url": "",
                    "has_back": False,
                    "back_url": None,
                    "faces": [],
                }
            payload["added"] = added
            return payload
        finally:
            conn.close()

    def _bucket_id_for_prefix(self, conn, bucket_prefix: str) -> Optional[str]:
        row = conn.execute(
            "SELECT bucket_id FROM buckets WHERE bucket_prefix = ? LIMIT 1",
            (bucket_prefix,),
        ).fetchone()
        return row["bucket_id"] if row else None

    def _load_sidecar(self, bucket_prefix: str) -> Dict[str, object]:
        sidecar_path = self.cfg.buckets_dir / f"bkt_{bucket_prefix}" / "sidecar.json"
        if not sidecar_path.exists():
            raise FileNotFoundError("Bucket sidecar missing")
        try:
            return json.loads(sidecar_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError("Invalid sidecar metadata") from exc

    def _select_variant(
        self, sidecar: Dict[str, object], requested: str
    ) -> Tuple[str, Optional[Dict[str, object]]]:
        variants = sidecar.get("data", {}).get("variants", [])
        if not isinstance(variants, list):
            variants = []
        requested_role = (requested or "").strip()
        if requested_role:
            for variant in variants:
                if variant.get("role") == requested_role:
                    return requested_role, variant
        for fallback in ("raw_front", "proxy_front"):
            for variant in variants:
                if variant.get("role") == fallback:
                    return fallback, variant
        return requested_role or "raw_front", None

    def _load_existing_bboxes(self, conn, bucket_id: str, variant_role: str) -> List[Tuple[float, float, float, float]]:
        rows = conn.execute(
            """
            SELECT left, top, width, height
            FROM face_embeddings
            WHERE bucket_id = ? AND variant_role = ?
            """,
            (bucket_id, variant_role),
        ).fetchall()
        return [
            (
                float(row["left"] or 0.0),
                float(row["top"] or 0.0),
                float(row["width"] or 0.0),
                float(row["height"] or 0.0),
            )
            for row in rows
        ]

    def _insert_face_detections(
        self,
        conn,
        bucket_id: str,
        variant_role: str,
        file_sha: str,
        detections: Sequence,
    ) -> int:
        if not detections:
            return 0
        row = conn.execute(
            "SELECT MAX(face_index) AS max_index FROM face_embeddings WHERE bucket_id = ? AND variant_role = ?",
            (bucket_id, variant_role),
        ).fetchone()
        start_index = int(row["max_index"] or -1) + 1 if row else 0
        rows = []
        for idx, detection in enumerate(detections):
            rows.append(
                (
                    bucket_id,
                    file_sha,
                    variant_role,
                    start_index + idx,
                    detection.bbox[0],
                    detection.bbox[1],
                    detection.bbox[2],
                    detection.bbox[3],
                    detection.confidence,
                    detection.embedding.tobytes(),
                    detection.embedding.shape[0],
                    json.dumps(detection.landmarks),
                )
            )
        if rows:
            conn.executemany(
                """
                INSERT INTO face_embeddings (
                    bucket_id,
                    file_sha256,
                    variant_role,
                    face_index,
                    left,
                    top,
                    width,
                    height,
                    confidence,
                    embedding,
                    embedding_dim,
                    landmarks
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()
        return len(rows)

    def _refresh_face_records(self, conn) -> None:
        records = load_face_records(
            conn,
            buckets_dir=self.cfg.buckets_dir,
            review_root=self.cfg.staging_root / "02_WORKING_BUCKETS",
            min_confidence=self.state.min_confidence,
            sources=self.sources,
        )
        ignored_ids = set(self.state.ignore_store.all().keys())
        filtered_records = [record for record in records if record.face_id not in ignored_ids]
        self.state.refresh_records(filtered_records)

    def _bucket_asset_url(self, bucket_prefix: str, filename: str) -> Optional[str]:
        if not bucket_prefix or not filename:
            return None
        relative_path = f"buckets/bkt_{bucket_prefix}/derived/{filename}"
        if not self._asset_exists(relative_path):
            return None
        return "/" + relative_path

    def _asset_exists(self, relative_path: str) -> bool:
        if not relative_path:
            return False
        root = Path(self.directory or ".").resolve()
        target = (root / relative_path.lstrip("/")).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            return False
        return target.exists()

    def _read_payload(self) -> Dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _coerce_bool(value, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            lowered = value.strip().lower()
            if not lowered:
                return default
            if lowered in {"1", "true", "yes", "on"}:
                return True
            if lowered in {"0", "false", "no", "off"}:
                return False
        return default

    def _write_json(self, data: Dict[str, object], status: int = 200) -> None:
        encoded = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def _record_payload(record: FaceRecord, similarity: Optional[float] = None) -> Dict[str, object]:
    bbox_left, bbox_top, bbox_width, bbox_height = record.bbox
    payload = {
        "face_id": record.face_id,
        "bucket_id": record.bucket_id,
        "bucket_prefix": record.bucket_prefix,
        "bucket_source": record.bucket_source,
        "variant": record.variant_role,
        "face_index": record.face_index,
        "confidence": record.confidence,
        "image": record.image,
        "image_url": record.image,
        "bbox": {
            "left": bbox_left,
            "top": bbox_top,
            "width": bbox_width,
            "height": bbox_height,
            "units": "fraction",
        },
        "bbox_xywh": {
            "x": bbox_left,
            "y": bbox_top,
            "w": bbox_width,
            "h": bbox_height,
            "units": "fraction",
        },
        "crop_url": None,
        "legacy_names": list(record.legacy_names),
    }
    if similarity is not None:
        payload["similarity"] = similarity
    return payload


def _normalize_manual_bbox(raw) -> Optional[Dict[str, float]]:
    if not isinstance(raw, dict):
        return None
    try:
        left = float(raw.get("left"))
        top = float(raw.get("top"))
        width = float(raw.get("width"))
        height = float(raw.get("height"))
    except (TypeError, ValueError):
        return None
    if any(value != value for value in (left, top, width, height)):
        return None
    left = max(0.0, min(1.0, left))
    top = max(0.0, min(1.0, top))
    width = max(0.0, min(1.0, width))
    height = max(0.0, min(1.0, height))
    if width <= 0 or height <= 0:
        return None
    if left + width > 1.0:
        width = max(0.0, 1.0 - left)
    if top + height > 1.0:
        height = max(0.0, 1.0 - top)
    if width <= 0 or height <= 0:
        return None
    return {"left": left, "top": top, "width": width, "height": height}


def _coerce_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _bbox_iou(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]) -> float:
    ax1, ay1, aw, ah = a
    bx1, by1, bw, bh = b
    ax2 = ax1 + aw
    ay2 = ay1 + ah
    bx2 = bx1 + bw
    by2 = by1 + bh
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h
    if inter_area <= 0:
        return 0.0
    union = aw * ah + bw * bh - inter_area
    if union <= 0:
        return 0.0
    return inter_area / union


def _load_oriented_bgr(path: Path, orientation: orientation_mod.OrientationInfo) -> np.ndarray:
    with Image.open(path) as img:
        oriented = orientation_mod.ensure_display_orientation(img, orientation)
        rgb = oriented.convert("RGB")
    array = np.array(rgb, dtype=np.uint8)
    return array[:, :, ::-1]


def run() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    run()
