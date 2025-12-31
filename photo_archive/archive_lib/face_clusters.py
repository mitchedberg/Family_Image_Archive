"""Offline clustering helpers for unlabeled faces."""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

import numpy as np

from .face_matcher import FaceMatcher, FaceRecord

MIN_CONF_FOR_CLUSTER = 0.75
MIN_AREA_FOR_CLUSTER = 0.003


@dataclass
class FaceClusterResult:
    clusters: List[Dict[str, object]]
    stats: Dict[str, object]


class FaceClusterBuilder:
    """Group nearby embeddings using random-projection LSH + union-find."""

    def __init__(
        self,
        matcher: FaceMatcher,
        excluded_face_ids: Iterable[str],
        *,
        similarity_threshold: float,
        min_faces: int = 3,
        bits_per_band: int = 12,
        band_count: int = 6,
        max_bucket_size: int = 600,
        random_seed: int = 1337,
        logger: Optional[logging.Logger] = None,
        min_confidence: float = MIN_CONF_FOR_CLUSTER,
        min_area: float = MIN_AREA_FOR_CLUSTER,
    ) -> None:
        if bits_per_band <= 0 or bits_per_band > 24:
            raise ValueError("bits_per_band must be between 1 and 24")
        if band_count <= 0 or band_count > 32:
            raise ValueError("band_count must be between 1 and 32")
        if min_faces < 2:
            raise ValueError("min_faces must be at least 2")
        if not 0.0 < similarity_threshold <= 1.0:
            raise ValueError("similarity_threshold must be between 0 and 1")
        self.matcher = matcher
        self.excluded_face_ids = {face_id.strip() for face_id in excluded_face_ids if face_id}
        self.threshold = float(similarity_threshold)
        self.min_faces = int(min_faces)
        self.bits_per_band = int(bits_per_band)
        self.band_count = int(band_count)
        self.max_bucket_size = int(max(2, max_bucket_size))
        self.min_confidence = float(min_confidence)
        self.min_area = float(min_area)
        self.logger = logger
        self._rng = np.random.default_rng(random_seed)
        self._bit_weights = (1 << np.arange(self.bits_per_band, dtype=np.uint32)).astype(np.uint32)

    def build(self) -> FaceClusterResult:
        eligible_indices = []
        for idx, record in enumerate(self.matcher.records):
            if record.face_id in self.excluded_face_ids:
                continue
            if record.confidence < self.min_confidence:
                continue
            area = record.bbox[2] * record.bbox[3]
            if area < self.min_area:
                continue
            eligible_indices.append(idx)

        stats: Dict[str, object] = {
            "eligible_faces": len(eligible_indices),
            "excluded_faces": len(self.excluded_face_ids),
            "similarity_threshold": self.threshold,
            "min_faces": self.min_faces,
            "band_count": self.band_count,
            "bits_per_band": self.bits_per_band,
            "min_confidence": self.min_confidence,
            "min_area": self.min_area,
        }
        if len(eligible_indices) < self.min_faces:
            stats.update({"clusters": 0, "clustered_faces": 0, "pair_links": 0})
            return FaceClusterResult([], stats)

        matrix = self.matcher.matrix[eligible_indices].astype(np.float32, copy=True)
        records = [self.matcher.records[idx] for idx in eligible_indices]
        uf = _UnionFind(len(records))
        lsh_stats = self._link_candidates(matrix, uf)
        clusters = self._clusters_from_union(matrix, records, uf)
        clustered_faces = sum(entry["face_count"] for entry in clusters)
        stats.update(lsh_stats)
        stats.update({
            "clusters": len(clusters),
            "clustered_faces": clustered_faces,
        })
        if self.logger:
            self.logger.info(
                "Face clusters built: eligible=%s clusters=%s threshold=%.2f",
                stats["eligible_faces"],
                len(clusters),
                self.threshold,
            )
        return FaceClusterResult(clusters, stats)

    def _link_candidates(self, matrix: np.ndarray, uf: "_UnionFind") -> Dict[str, int]:
        n, dim = matrix.shape
        pair_attempts = pair_links = 0
        bucket_examined = bucket_skipped = 0
        checked_pairs: Set[int] = set()
        for _ in range(self.band_count):
            planes = self._rng.standard_normal(size=(self.bits_per_band, dim), dtype=np.float32)
            projections = matrix @ planes.T
            signatures = (projections >= 0).astype(np.uint32)
            hashes = (signatures * self._bit_weights).sum(axis=1, dtype=np.uint32)
            buckets: Dict[int, List[int]] = {}
            for row_idx, code in enumerate(hashes.tolist()):
                buckets.setdefault(code, []).append(row_idx)
            for indices in buckets.values():
                if len(indices) < 2:
                    continue
                bucket_examined += 1
                if len(indices) > self.max_bucket_size:
                    bucket_skipped += 1
                    continue
                indices.sort()
                for pos, anchor_idx in enumerate(indices[:-1]):
                    anchor_vec = matrix[anchor_idx]
                    for target_idx in indices[pos + 1 :]:
                        pair_key = _pair_key(anchor_idx, target_idx)
                        if pair_key in checked_pairs:
                            continue
                        checked_pairs.add(pair_key)
                        pair_attempts += 1
                        similarity = float(np.dot(anchor_vec, matrix[target_idx]))
                        if similarity < self.threshold:
                            continue
                        uf.union(anchor_idx, target_idx)
                        pair_links += 1
        return {
            "pair_attempts": pair_attempts,
            "pair_links": pair_links,
            "bucket_examined": bucket_examined,
            "bucket_skipped": bucket_skipped,
        }

    def _clusters_from_union(
        self,
        matrix: np.ndarray,
        records: Sequence[FaceRecord],
        uf: "_UnionFind",
    ) -> List[Dict[str, object]]:
        groups: Dict[int, List[int]] = {}
        for idx in range(len(records)):
            root = uf.find(idx)
            groups.setdefault(root, []).append(idx)
        entries: List[Dict[str, object]] = []
        for member_indices in groups.values():
            if len(member_indices) < self.min_faces:
                continue
            entries.append(self._cluster_entry(matrix, records, member_indices))
        entries.sort(key=lambda entry: (-entry["face_count"], -entry["bucket_count"], entry["cluster_id"]))
        return entries

    def _cluster_entry(
        self,
        matrix: np.ndarray,
        records: Sequence[FaceRecord],
        member_indices: Sequence[int],
    ) -> Dict[str, object]:
        sorted_indices = sorted(
            member_indices,
            key=lambda idx: (records[idx].bucket_prefix, records[idx].face_index, records[idx].face_id),
        )
        member_records = [records[idx] for idx in sorted_indices]
        face_ids = [record.face_id for record in member_records]
        bucket_prefixes = sorted({record.bucket_prefix for record in member_records})
        rep_idx = self._representative_index(matrix, member_indices)
        rep_record = records[rep_idx]
        stats = self._cluster_stats(matrix, member_indices, records)
        representative = {
            "face_id": rep_record.face_id,
            "bucket_prefix": rep_record.bucket_prefix,
            "image_url": rep_record.image,
            "bbox": {
                "left": rep_record.bbox[0],
                "top": rep_record.bbox[1],
                "width": rep_record.bbox[2],
                "height": rep_record.bbox[3],
            },
            "confidence": rep_record.confidence,
        }
        return {
            "cluster_id": _cluster_id(face_ids),
            "member_face_ids": face_ids,
            "bucket_prefixes": bucket_prefixes,
            "bucket_count": len(bucket_prefixes),
            "face_count": len(face_ids),
            "representative": representative,
            "stats": stats,
        }

    def _representative_index(self, matrix: np.ndarray, member_indices: Sequence[int]) -> int:
        if len(member_indices) == 1:
            return member_indices[0]
        cluster_matrix = matrix[list(member_indices)]
        similarity_matrix = cluster_matrix @ cluster_matrix.T
        scores = similarity_matrix.sum(axis=1)
        best_local = int(np.argmax(scores))
        return member_indices[best_local]

    def _cluster_stats(
        self,
        matrix: np.ndarray,
        member_indices: Sequence[int],
        records: Sequence[FaceRecord],
    ) -> Dict[str, float]:
        confidences = [records[idx].confidence for idx in member_indices]
        stats = {
            "max_confidence": max(confidences) if confidences else 0.0,
            "min_confidence": min(confidences) if confidences else 0.0,
            "avg_confidence": sum(confidences) / len(confidences) if confidences else 0.0,
        }
        if len(member_indices) < 2:
            stats["avg_similarity"] = 1.0
            return stats
        cluster_matrix = matrix[list(member_indices)]
        similarity_matrix = cluster_matrix @ cluster_matrix.T
        upper = np.triu_indices(similarity_matrix.shape[0], k=1)
        if upper[0].size == 0:
            stats["avg_similarity"] = 1.0
        else:
            stats["avg_similarity"] = float(np.mean(similarity_matrix[upper]))
        return stats


class FaceClusterStore:
    """JSON-backed cache for cluster entries."""

    VERSION = 1

    def __init__(self, path: Path) -> None:
        self.path = path
        self._data: Dict[str, object] = {}
        self._clusters: List[Dict[str, object]] = []
        self._cluster_index: Dict[str, Dict[str, object]] = {}
        self._load()

    def clusters(self) -> List[Dict[str, object]]:
        return list(self._clusters)

    def get(self, cluster_id: str) -> Optional[Dict[str, object]]:
        entry = self._cluster_index.get(cluster_id)
        if entry is None:
            return None
        return entry

    def metadata(self) -> Dict[str, object]:
        generated_at = self._data.get("generated_at")
        generated_iso = self._data.get("generated_at_iso")
        return {
            "generated_at": generated_at,
            "generated_at_iso": generated_iso,
            "signature": self._data.get("signature", ""),
            "params": self._data.get("params", {}),
            "stats": self._data.get("stats", {}),
            "cluster_count": len(self._clusters),
        }

    def signature(self) -> str:
        return str(self._data.get("signature") or "")

    def is_compatible(self, signature: str) -> bool:
        if not signature:
            return False
        return bool(self._clusters) and self.signature() == signature

    def write(
        self,
        clusters: Sequence[Dict[str, object]],
        *,
        signature: str,
        params: Optional[Dict[str, object]] = None,
        stats: Optional[Dict[str, object]] = None,
    ) -> None:
        payload = {
            "version": self.VERSION,
            "generated_at": int(time.time()),
            "generated_at_iso": datetime.now(timezone.utc).isoformat(),
            "signature": signature,
            "params": params or {},
            "stats": stats or {},
            "clusters": list(clusters),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(self.path)
        self._data = payload
        self._clusters = list(clusters)
        self._rebuild_index()

    def _load(self) -> None:
        if not self.path.exists():
            self._data = {
                "version": self.VERSION,
                "generated_at": None,
                "generated_at_iso": None,
                "signature": "",
                "params": {},
                "stats": {},
                "clusters": [],
            }
            self._clusters = []
            self._cluster_index = {}
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        clusters = payload.get("clusters")
        if isinstance(clusters, list):
            self._clusters = clusters
        else:
            self._clusters = []
        self._data = payload
        self._rebuild_index()

    def _rebuild_index(self) -> None:
        self._cluster_index = {}
        for entry in self._clusters:
            cluster_id = entry.get("cluster_id")
            if isinstance(cluster_id, str):
                self._cluster_index[cluster_id] = entry


class _UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))
        self.rank = [0] * size

    def find(self, item: int) -> int:
        if self.parent[item] != item:
            self.parent[item] = self.find(self.parent[item])
        return self.parent[item]

    def union(self, a: int, b: int) -> None:
        root_a = self.find(a)
        root_b = self.find(b)
        if root_a == root_b:
            return
        if self.rank[root_a] < self.rank[root_b]:
            self.parent[root_a] = root_b
        elif self.rank[root_a] > self.rank[root_b]:
            self.parent[root_b] = root_a
        else:
            self.parent[root_b] = root_a
            self.rank[root_a] += 1


def _pair_key(a: int, b: int) -> int:
    lo = min(a, b)
    hi = max(a, b)
    return (lo << 32) | hi


def _cluster_id(face_ids: Sequence[str]) -> str:
    normalized = "|".join(sorted(face_ids))
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()
    return digest[:12]

