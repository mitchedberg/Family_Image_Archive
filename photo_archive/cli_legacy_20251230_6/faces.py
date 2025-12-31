"""CLI helpers for generating face embeddings on original images."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import typer
import numpy as np
from PIL import Image

from archive_lib import config as config_mod, db as db_mod, log as log_mod
from archive_lib.faces import FaceRecognizer, FaceStorage
from archive_lib.reporting import BucketInfo, load_bucket_infos
from archive_lib import orientation as orientation_mod

app = typer.Typer(add_completion=False)


@app.command()
def extract(
    source: Optional[str] = typer.Option(None, "--source", help="Limit to this source label"),
    bucket_prefix: Optional[List[str]] = typer.Option(
        None,
        "--bucket-prefix",
        help="Only process the requested bucket prefixes (repeatable)",
    ),
    limit: Optional[int] = typer.Option(None, "--limit", help="Stop after N buckets"),
    model_dir: Optional[Path] = typer.Option(
        None,
        "--model-dir",
        help="Custom directory for YuNet/SFace ONNX models (defaults to 03_MODELS/faces)",
    ),
    min_score: float = typer.Option(0.45, "--min-score", help="Minimum detector score to keep a face"),
    max_faces: int = typer.Option(10, "--max-faces", help="Maximum faces to store per bucket"),
    max_dimension: int = typer.Option(
        3600,
        "--max-dimension",
        help="Resize originals so the longest edge matches this size before detection",
    ),
    force: bool = typer.Option(False, "--force/--skip-existing", help="Rebuild even if embeddings already exist"),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging verbosity"),
) -> None:
    """Detect faces on raw originals and store embeddings for later search."""

    if max_faces <= 0:
        raise typer.BadParameter("--max-faces must be greater than zero")
    if min_score <= 0 or min_score >= 1.0:
        raise typer.BadParameter("--min-score must be between 0 and 1")
    if max_dimension <= 0:
        raise typer.BadParameter("--max-dimension must be greater than zero")

    log_mod.setup_logging(log_level)
    logger = logging.getLogger("cli.faces")
    cfg = config_mod.load_config()
    conn = db_mod.connect(cfg.db_path)
    infos = load_bucket_infos(conn, cfg, source=source)
    if bucket_prefix:
        requested = set(bucket_prefix)
        infos = [info for info in infos if info.bucket_prefix in requested]
    if not infos:
        typer.echo("No eligible buckets found for the requested filters", err=True)
        raise typer.Exit(code=1)

    models_root = model_dir or (cfg.staging_root / "03_MODELS" / "faces")
    recognizer = FaceRecognizer(models_root, logger=logger)
    storage = FaceStorage(conn, logger=logger)

    if limit is not None:
        if force:
            infos = infos[:limit]
        else:
            pending: List[BucketInfo] = []
            for info in infos:
                if storage.has_faces(info.bucket_id, "raw_front") or storage.has_faces(info.bucket_id, "proxy_front"):
                    continue
                pending.append(info)
                if len(pending) >= limit:
                    break
            infos = pending
            if not infos:
                typer.echo("No remaining buckets without embeddings. Use --force to rescan the earliest ones.")
                raise typer.Exit(code=0)

    processed = stored = skipped = 0
    total_faces = 0
    for info in infos:
        variant_map = _variant_index(info)
        variant_role, variant = _select_detection_variant(variant_map)
        if not variant_role or not variant:
            skipped += 1
            continue
        raw_path = Path(str(variant.get("path") or ""))
        if not raw_path.exists():
            logger.warning("Raw file missing for %s (%s)", info.bucket_id, raw_path)
            skipped += 1
            continue
        file_sha = variant.get("sha256")
        if not file_sha:
            logger.warning("No sha256 recorded for %s", info.bucket_id)
            skipped += 1
            continue
        if not force and storage.has_faces(info.bucket_id, variant_role):
            continue
        orientation_info = orientation_mod.extract_orientation_info(info)
        try:
            image_data = _load_oriented_bgr(raw_path, orientation_info)
        except Exception as exc:  # pragma: no cover - orientation bugs
            logger.warning("Orientation prep failed for %s: %s", info.bucket_id, exc)
            skipped += 1
            continue
        try:
            detections = recognizer.process_image(
                raw_path,
                min_score=min_score,
                max_faces=max_faces,
                max_dimension=max_dimension,
                image_data=image_data,
            )
        except Exception as exc:  # pragma: no cover - safety net
            logger.warning("Face extraction failed for %s: %s", info.bucket_id, exc)
            skipped += 1
            continue
        storage.replace_faces(info.bucket_id, variant_role, file_sha, detections)
        processed += 1
        stored += int(bool(detections))
        total_faces += len(detections)
        logger.debug(
            "Processed %s (%s) → %d faces",
            info.bucket_id,
            raw_path.name,
            len(detections),
        )

    typer.echo(
        f"Examined {len(infos)} buckets | processed={processed} stored={stored} skipped={skipped} faces={total_faces}"
    )


def _variant_index(info: BucketInfo) -> Dict[str, Dict[str, object]]:
    index: Dict[str, Dict[str, object]] = {}
    for variant in info.variants:
        role = variant.get("role")
        if role and role not in index:
            index[role] = variant
    return index


def _select_detection_variant(variant_map: Dict[str, Dict[str, object]]) -> Tuple[Optional[str], Optional[Dict[str, object]]]:
    """Prefer raw fronts but fall back to proxies if needed."""

    for role in ("raw_front", "proxy_front"):
        candidate = variant_map.get(role)
        if candidate:
            return role, candidate
    return None, None


def _load_oriented_bgr(path: Path, orientation: orientation_mod.OrientationInfo) -> np.ndarray:
    with Image.open(path) as img:
        oriented = orientation_mod.ensure_display_orientation(img, orientation)
        rgb = oriented.convert("RGB")
    array = np.array(rgb, dtype=np.uint8)
    # Convert RGB -> BGR for OpenCV consumers
    return array[:, :, ::-1]


def run() -> None:  # pragma: no cover - console entry
    typer.run(extract)


if __name__ == "__main__":  # pragma: no cover
    run()
