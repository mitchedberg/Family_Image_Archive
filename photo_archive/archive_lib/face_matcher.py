"""Helpers for nearest-neighbor face suggestions."""
from __future__ import annotations

import json
import math
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np


@dataclass
class FaceRecord:
    face_id: str
    bucket_id: str
    bucket_prefix: str
    bucket_source: str
    variant_role: str
    face_index: int
    confidence: float
    embedding: np.ndarray
    image: str
    bbox: Tuple[float, float, float, float]
    legacy_names: Tuple[str, ...]


LEGACY_CONFIDENCE_MAX = 1.01


class FaceMatcher:
    """In-memory cache of embeddings with cosine-similarity helpers."""

    def __init__(self, records: Sequence[FaceRecord]):
        if not records:
            raise ValueError("No face embeddings available")
        self.records = list(records)
        self.index_by_id: Dict[str, int] = {}
        vectors: List[np.ndarray] = []
        for idx, record in enumerate(self.records):
            self.index_by_id[record.face_id] = idx
            vectors.append(record.embedding)
        self.matrix = np.stack(vectors, axis=0)

    @property
    def count(self) -> int:
        return len(self.records)

    def embedding_for(self, face_id: str) -> Optional[np.ndarray]:
        idx = self.index_by_id.get(face_id)
        if idx is None:
            return None
        return self.matrix[idx]

    def centroid(self, face_ids: Iterable[str]) -> Optional[np.ndarray]:
        vectors = [self.embedding_for(face_id) for face_id in face_ids if self.embedding_for(face_id) is not None]
        if not vectors:
            return None
        stacked = np.stack(vectors, axis=0)
        mean = stacked.mean(axis=0)
        norm = np.linalg.norm(mean)
        if not norm:
            return None
        return mean / norm

    def next_candidate(
        self,
        positives: Iterable[str],
        excluded_ids: Iterable[str],
        rejected_ids: Iterable[str],
        *,
        min_similarity: float,
        min_confidence: float,
        bucket_conf_overrides: Optional[Dict[str, float]] = None,
    ) -> Optional[Tuple[FaceRecord, float]]:
        anchor = self.centroid(positives)
        if anchor is None:
            return None
        scores = self.matrix @ anchor
        order = np.argsort(scores)[::-1]
        excluded = set(excluded_ids)
        rejected = set(rejected_ids)
        positives_set = set(positives)
        overrides = bucket_conf_overrides or {}
        for idx in order:
            score = float(scores[idx])
            if score < min_similarity:
                break
            record = self.records[idx]
            if record.face_id in excluded or record.face_id in rejected or record.face_id in positives_set:
                continue
            
            cutoff = overrides.get(record.bucket_prefix, min_confidence)
            if record.confidence < cutoff:
                continue
            return record, score
        return None

    def ranked_candidates(
        self,
        positives: Iterable[str],
        excluded_ids: Iterable[str],
        rejected_ids: Iterable[str],
        *,
        min_similarity: float,
        min_confidence: float,
        limit: int,
        bucket_conf_overrides: Optional[Dict[str, float]] = None,
    ) -> List[Tuple[FaceRecord, float]]:
        if limit <= 0:
            return []
        anchor = self.centroid(positives)
        if anchor is None:
            return []
        scores = self.matrix @ anchor
        order = np.argsort(scores)[::-1]
        excluded = set(excluded_ids)
        rejected = set(rejected_ids)
        positives_set = set(positives)
        overrides = bucket_conf_overrides or {}
        results: List[Tuple[FaceRecord, float]] = []
        for idx in order:
            if len(results) >= limit:
                break
            score = float(scores[idx])
            if score < min_similarity:
                break
            record = self.records[idx]
            if record.face_id in excluded or record.face_id in rejected or record.face_id in positives_set:
                continue
            
            cutoff = overrides.get(record.bucket_prefix, min_confidence)
            if record.confidence < cutoff:
                continue
            results.append((record, score))
        return results

    def record_for(self, face_id: str) -> Optional[FaceRecord]:
        idx = self.index_by_id.get(face_id)
        if idx is None:
            return None
        return self.records[idx]


def load_face_records(
    conn,
    *,
    buckets_dir: Path,
    review_root: Path,
    min_confidence: float = 0.0,
    sources: Optional[Sequence[str]] = None,
    limit: Optional[int] = None,
) -> List[FaceRecord]:
    sql = """
        SELECT
            f.bucket_id,
            f.variant_role,
            f.face_index,
            f.confidence,
            f.embedding,
            f.embedding_dim,
            f.left,
            f.top,
            f.width,
            f.height,
            b.bucket_prefix,
            b.source
        FROM face_embeddings AS f
        JOIN buckets AS b ON b.bucket_id = f.bucket_id
        WHERE f.variant_role IN ('raw_front', 'proxy_front')
          AND f.embedding IS NOT NULL
          AND f.embedding <> ''
          AND f.confidence >= ?
    """
    params: List[object] = [min_confidence]
    if sources:
        placeholders = ",".join("?" for _ in sources)
        sql += f" AND b.source IN ({placeholders})"
        params.extend(sources)
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    records: List[FaceRecord] = []
    for row in rows:
        confidence = float(row["confidence"] or 0.0)
        if confidence > LEGACY_CONFIDENCE_MAX:
            continue
        bucket_prefix = row["bucket_prefix"]
        image_path = _resolve_image_path(buckets_dir, bucket_prefix)
        if image_path is None:
            continue
        embedding = _decode_embedding(row["embedding"], row["embedding_dim"])
        if embedding is None:
            continue
        face_id = f"{bucket_prefix}:{row['face_index']}"
        legacy_names = _extract_legacy_names(buckets_dir, bucket_prefix)
        records.append(
            FaceRecord(
                face_id=face_id,
                bucket_id=row["bucket_id"],
                bucket_prefix=bucket_prefix,
                bucket_source=row["source"],
                variant_role=row["variant_role"],
                face_index=int(row["face_index"]),
                confidence=confidence,
                embedding=embedding,
                image=_relpath(image_path, review_root),
                bbox=(
                    float(row["left"] or 0.0),
                    float(row["top"] or 0.0),
                    float(row["width"] or 0.0),
                    float(row["height"] or 0.0),
                ),
                legacy_names=legacy_names,
            )
        )
    return records


def _decode_embedding(blob, dim) -> Optional[np.ndarray]:
    if blob is None:
        return None
    vector = np.frombuffer(blob, dtype=np.float32)
    if dim and dim > 0:
        vector = vector[:dim]
    norm = np.linalg.norm(vector)
    if not norm or math.isclose(norm, 0.0):
        return None
    return vector / norm


def _resolve_image_path(buckets_dir: Path, bucket_prefix: str) -> Optional[Path]:
    bucket_dir = buckets_dir / f"bkt_{bucket_prefix}"
    derived = bucket_dir / "derived"
    candidate = derived / "web_front.jpg"
    if candidate.exists():
        return candidate
    return None


def _relpath(path: Path, root: Path) -> str:
    rel = path.relative_to(root).as_posix()
    return f"/{rel}"


def _extract_legacy_names(buckets_dir: Path, bucket_prefix: str) -> Tuple[str, ...]:
    sidecar = buckets_dir / f"bkt_{bucket_prefix}" / "sidecar.json"
    if not sidecar.exists():
        return ()
    try:
        data = json.loads(sidecar.read_text())
    except Exception:
        return ()
    photos = (data.get("data") or {}).get("photos_asset") or {}
    persons = photos.get("persons") or []
    if not isinstance(persons, list):
        return ()
    cleaned = tuple(
        str(name).strip()
        for name in persons
        if isinstance(name, str) and str(name).strip()
    )
    return cleaned
