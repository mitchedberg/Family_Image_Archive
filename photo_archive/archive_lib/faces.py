"""Face detection + embedding helpers backed by OpenCV's YuNet + SFace models."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple, Optional
from urllib.error import URLError
from urllib.request import urlretrieve

import cv2  # type: ignore
import numpy as np

MODEL_SPECS = {
    "detector": {
        "filename": "face_detection_yunet_2023mar.onnx",
        "url": "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    },
    "recognizer": {
        "filename": "face_recognition_sface_2021dec.onnx",
        "url": "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
    },
}

MIN_FACE_DIMENSION_RATIO = 0.01
MIN_FACE_AREA_RATIO = 0.0005


@dataclass
class FaceDetection:
    bbox: Tuple[float, float, float, float]
    confidence: float
    embedding: np.ndarray
    landmarks: Tuple[Tuple[float, float], ...]


class FaceRecognizer:
    """Detect and embed faces from high-resolution originals."""

    def __init__(self, model_dir: Path, *, logger: logging.Logger) -> None:
        self.logger = logger
        self.model_dir = model_dir
        detector_path, recognizer_path = self._ensure_models()
        self.detector = cv2.FaceDetectorYN_create(
            str(detector_path),
            "",
            (320, 320),
            score_threshold=0.5,
            nms_threshold=0.3,
            top_k=5000,
        )
        self.recognizer = cv2.FaceRecognizerSF_create(str(recognizer_path), "")

    def _ensure_models(self) -> Tuple[Path, Path]:
        self.model_dir.mkdir(parents=True, exist_ok=True)
        resolved: dict[str, Path] = {}
        for key, spec in MODEL_SPECS.items():
            target = self.model_dir / spec["filename"]
            if not target.exists():
                self.logger.info("Downloading %s to %s", spec["filename"], target)
                try:
                    urlretrieve(spec["url"], target)
                except URLError as exc:  # pragma: no cover - network failures
                    raise RuntimeError(f"Failed to download {spec['filename']}") from exc
            resolved[key] = target
        return resolved["detector"], resolved["recognizer"]

    def process_image(
        self,
        image_path: Path,
        *,
        min_score: float,
        max_faces: int,
        max_dimension: int,
        image_data: Optional[np.ndarray] = None,
    ) -> List[FaceDetection]:
        if image_data is not None:
            image = image_data
        else:
            image = cv2.imread(str(image_path))
        if image is None:
            raise ValueError(f"Unable to read image: {image_path}")
        orig_height, orig_width = image.shape[:2]
        scale = 1.0
        largest = max(orig_height, orig_width)
        if max_dimension and largest > max_dimension:
            scale = max_dimension / float(largest)
            resized = cv2.resize(
                image,
                (max(1, int(round(orig_width * scale))), max(1, int(round(orig_height * scale)))),
            )
        else:
            resized = image
        height, width = resized.shape[:2]
        self.detector.setInputSize((width, height))
        self.detector.setScoreThreshold(float(min_score))
        _, raw_faces = self.detector.detect(resized)
        if raw_faces is None or not len(raw_faces):
            return []
        faces = np.array(raw_faces)
        score_index = -1
        order = np.argsort(faces[:, score_index])[::-1]
        faces = faces[order]
        if max_faces:
            faces = faces[:max_faces]
        results: List[FaceDetection] = []
        for face in faces:
            score = float(face[score_index])
            if score < min_score:
                continue
            try:
                aligned = self.recognizer.alignCrop(resized, face)
                embedding = self.recognizer.feature(aligned).reshape(-1)
            except cv2.error as exc:  # pragma: no cover - OpenCV internal failures
                self.logger.debug("Embedding failed for %s: %s", image_path, exc)
                continue
            bbox = _normalize_bbox(face[:4], orig_width, orig_height, scale)
            landmarks = _normalize_landmarks(face[4:score_index], orig_width, orig_height, scale)
            if _bbox_too_small(bbox):
                continue
            results.append(
                FaceDetection(
                    bbox=bbox,
                    confidence=score,
                    embedding=embedding.astype(np.float32),
                    landmarks=landmarks,
                )
            )
        return results


class FaceStorage:
    """Persist face embeddings into the archive database."""

    def __init__(self, conn, *, logger: logging.Logger) -> None:
        self.conn = conn
        self.logger = logger

    def has_faces(self, bucket_id: str, variant_role: str) -> bool:
        row = self.conn.execute(
            """
            SELECT 1
            FROM face_embeddings
            WHERE bucket_id = ? AND variant_role = ?
            LIMIT 1
            """,
            (bucket_id, variant_role),
        ).fetchone()
        return bool(row)

    def replace_faces(
        self,
        bucket_id: str,
        variant_role: str,
        file_sha256: str,
        faces: Sequence[FaceDetection],
    ) -> None:
        self.conn.execute(
            "DELETE FROM face_embeddings WHERE bucket_id = ? AND variant_role = ?",
            (bucket_id, variant_role),
        )
        rows = [
            (
                bucket_id,
                file_sha256,
                variant_role,
                idx,
                detection.bbox[0],
                detection.bbox[1],
                detection.bbox[2],
                detection.bbox[3],
                detection.confidence,
                detection.embedding.tobytes(),
                detection.embedding.shape[0],
                json.dumps(detection.landmarks),
            )
            for idx, detection in enumerate(faces)
        ]
        if rows:
            self.conn.executemany(
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
        self.conn.commit()
        self.logger.debug("Stored %d faces for %s (%s)", len(rows), bucket_id, variant_role)


def _bbox_too_small(bbox: Tuple[float, float, float, float]) -> bool:
    _, _, width, height = bbox
    if width <= 0 or height <= 0:
        return True
    if width < MIN_FACE_DIMENSION_RATIO or height < MIN_FACE_DIMENSION_RATIO:
        return True
    if width * height < MIN_FACE_AREA_RATIO:
        return True
    return False


def _normalize_bbox(
    bbox: Iterable[float],
    orig_width: int,
    orig_height: int,
    scale: float,
) -> Tuple[float, float, float, float]:
    x, y, width, height = [float(value) for value in bbox]
    if scale:
        inv = 1.0 / scale
        x *= inv
        y *= inv
        width *= inv
        height *= inv
    left = _clamp_ratio(x, orig_width)
    top = _clamp_ratio(y, orig_height)
    norm_width = _clamp_ratio(width, orig_width)
    norm_height = _clamp_ratio(height, orig_height)
    return (left, top, norm_width, norm_height)


def _normalize_landmarks(
    coords: Sequence[float],
    orig_width: int,
    orig_height: int,
    scale: float,
) -> Tuple[Tuple[float, float], ...]:
    points: List[Tuple[float, float]] = []
    inv = 1.0 / scale if scale else 1.0
    for idx in range(0, min(len(coords), 10), 2):
        x = coords[idx] * inv
        y = coords[idx + 1] * inv
        points.append((_clamp_ratio(x, orig_width), _clamp_ratio(y, orig_height)))
    return tuple(points)


def _clamp_ratio(value: float, denom: int) -> float:
    if denom <= 0:
        return 0.0
    ratio = value / float(denom)
    return max(0.0, min(1.0, ratio))
