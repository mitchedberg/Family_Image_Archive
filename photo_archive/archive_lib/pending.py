"""Helpers for reporting and reconciling pending AI variants."""
from __future__ import annotations

import csv
import json
import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .config import AppConfig
from .imaging import dhash
from .ingest.assigner import BUCKET_PREFIX_LENGTH, extract_fastfoto_token, extract_img_token

PRO4K_RE = re.compile(r"pro[_-]?4k[_-]?(\d+)", re.IGNORECASE)
HEX_RE = re.compile(r"\b[0-9a-f]{8,16}\b", re.IGNORECASE)
PHASH_THRESHOLD = 10


@dataclass
class AIPendingRow:
    sha256: str
    role: str
    join_key: Optional[str]
    fastfoto_token: Optional[str]
    img_token: Optional[str]
    notes: Optional[str]
    created_at: str
    path: Path
    basename: str

    @property
    def parsed_tokens(self) -> "PendingTokens":
        return parse_tokens(self.basename)


@dataclass
class PendingTokens:
    pro4k_token: Optional[str]
    img_token: Optional[str]
    hex_tokens: List[str]
    filename_fastfoto: Optional[str]


@dataclass
class CanonicalIndex:
    bucket_prefix_map: Dict[str, str]
    fastfoto_map: Dict[str, str]
    img_token_map: Dict[str, str]
    img_token_conflicts: Dict[str, List[str]]
    stem_map: Dict[str, List[str]]
    bucket_prefix_lookup: Dict[str, str]
    canonical_paths: Dict[str, Path]


@dataclass
class OverrideRow:
    ai_sha256: str
    attach_bucket_prefix: str
    note: str
    source: Optional[str]


@dataclass
class OverrideResult:
    ai_sha256: str
    bucket_prefix: str
    status: str
    message: str


def analyze_ai_pending(
    conn: sqlite3.Connection,
    cfg: AppConfig,
    *,
    source: str,
    enable_phash: bool,
    logger: logging.Logger,
) -> None:
    rows = _fetch_pending_rows(conn, source)
    if not rows:
        logger.info("No pending AI variants for %s", source)
    index = _build_canonical_index(conn, cfg, source)
    candidates: List[Tuple[AIPendingRow, str, str, str]] = []
    ambiguous: List[Tuple[AIPendingRow, List[str], str]] = []
    no_signal: List[Tuple[AIPendingRow, str]] = []

    for row in rows:
        tokens = row.parsed_tokens
        result = _match_row(row, tokens, index)
        if result.status == "match":
            candidates.append((row, result.bucket_id, result.reason, result.confidence))
        elif result.status == "ambiguous":
            ambiguous.append((row, result.bucket_candidates, result.reason))
        else:
            no_signal.append((row, result.reason))

    _write_ai_pending_reports(cfg.reports_dir, candidates, ambiguous, no_signal)

    if enable_phash:
        _write_phash_candidates(rows, index, cfg.reports_dir, logger)


def load_ai_overrides(path: Path) -> List[OverrideRow]:
    if not path.exists():
        return []
    rows: List[OverrideRow] = []
    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            sha = (raw.get("ai_sha256") or "").strip().lower()
            prefix = (raw.get("attach_bucket_prefix") or "").strip().lower()
            note = (raw.get("note") or "").strip()
            override_source = (raw.get("source") or "").strip().lower() or None
            if not sha or not prefix:
                continue
            rows.append(
                OverrideRow(ai_sha256=sha, attach_bucket_prefix=prefix, note=note, source=override_source)
            )
    return rows


@dataclass
class OverrideSummary:
    applied: int
    skipped: int
    results_path: Path


def apply_ai_overrides(
    conn: sqlite3.Connection,
    cfg: AppConfig,
    *,
    source: str,
    overrides: Sequence[OverrideRow],
    logger: logging.Logger,
) -> OverrideSummary:
    results: List[OverrideResult] = []
    applied = 0
    for override in overrides:
        if override.source and override.source != source:
            continue
        pending = conn.execute(
            """
            SELECT pv.file_sha256, pv.role
            FROM pending_variants pv
            WHERE pv.file_sha256 = ? AND pv.source = ?
            """,
            (override.ai_sha256, source),
        ).fetchone()
        if not pending:
            results.append(
                OverrideResult(
                    ai_sha256=override.ai_sha256,
                    bucket_prefix=override.attach_bucket_prefix,
                    status="skipped",
                    message="pending_not_found",
                )
            )
            continue
        bucket = conn.execute(
            """
            SELECT bucket_id FROM buckets
            WHERE bucket_prefix = ? AND source = ?
            """,
            (override.attach_bucket_prefix, source),
        ).fetchone()
        if not bucket:
            results.append(
                OverrideResult(
                    ai_sha256=override.ai_sha256,
                    bucket_prefix=override.attach_bucket_prefix,
                    status="skipped",
                    message="bucket_not_found",
                )
            )
            continue
        bucket_id = bucket["bucket_id"]
        logger.info("Attaching %s to bucket %s", override.ai_sha256[:8], bucket_id[:BUCKET_PREFIX_LENGTH])
        conn.execute(
            """
            INSERT INTO bucket_files (bucket_id, file_sha256, role, is_primary, notes)
            VALUES (?, ?, ?, 0, ?)
            ON CONFLICT(bucket_id, role, file_sha256) DO NOTHING
            """,
            (
                bucket_id,
                override.ai_sha256,
                pending["role"],
                json.dumps(["ai_override"]),
            ),
        )
        conn.execute("DELETE FROM pending_variants WHERE file_sha256 = ?", (override.ai_sha256,))
        conn.commit()
        applied += 1
        results.append(
            OverrideResult(
                ai_sha256=override.ai_sha256,
                bucket_prefix=override.attach_bucket_prefix,
                status="applied",
                message="attached",
            )
        )
    results_path = cfg.reports_dir / "ai_overrides_applied.csv"
    _write_override_results(results_path, results)
    return OverrideSummary(applied=applied, skipped=len(results) - applied, results_path=results_path)


# Internal helpers -----------------------------------------------------


def _fetch_pending_rows(conn: sqlite3.Connection, source: str) -> List[AIPendingRow]:
    cursor = conn.execute(
        """
        SELECT pv.file_sha256,
               pv.role,
               pv.join_key,
               pv.fastfoto_token,
               pv.img_token,
               pv.notes,
               pv.created_at,
               f.staged_path,
               f.path,
               f.original_filename
        FROM pending_variants pv
        JOIN files f ON f.sha256 = pv.file_sha256
        WHERE pv.source = ? AND pv.role LIKE 'ai_%'
        ORDER BY pv.created_at
        """,
        (source,),
    )
    rows = []
    for row in cursor.fetchall():
        path_str = row["staged_path"] or row["path"]
        if not path_str:
            continue
        file_path = Path(path_str)
        rows.append(
            AIPendingRow(
                sha256=row["file_sha256"],
                role=row["role"],
                join_key=row["join_key"],
                fastfoto_token=row["fastfoto_token"],
                img_token=row["img_token"],
                notes=row["notes"],
                created_at=row["created_at"],
                path=file_path,
                basename=(row["original_filename"] or file_path.name),
            )
        )
    cursor.close()
    return rows


def _build_canonical_index(conn: sqlite3.Connection, cfg: AppConfig, source: str) -> CanonicalIndex:
    prefix_map: Dict[str, str] = {}
    fastfoto_map: Dict[str, str] = {}
    img_token_candidates: Dict[str, List[str]] = {}
    stem_map: Dict[str, List[str]] = {}
    canonical_paths: Dict[str, Path] = {}

    def register_img_token(token: Optional[str], bucket_id: str) -> None:
        if not token:
            return
        token_norm = token.lower()
        buckets = img_token_candidates.setdefault(token_norm, [])
        if bucket_id not in buckets:
            buckets.append(bucket_id)

    cursor = conn.execute(
        """
        SELECT b.bucket_id, b.bucket_prefix, bf.role, f.original_filename, f.staged_path, f.path
        FROM buckets b
        JOIN bucket_files bf ON bf.bucket_id = b.bucket_id
        JOIN files f ON f.sha256 = bf.file_sha256
        WHERE b.source = ? AND bf.role IN ('raw_front', 'proxy_front')
        ORDER BY bf.role = 'raw_front'
        """,
        (source,),
    )
    for row in cursor.fetchall():
        bucket_id = row["bucket_id"]
        prefix = row["bucket_prefix"]
        prefix_map[prefix.lower()] = bucket_id
        bucket_dir = cfg.buckets_dir / f"bkt_{prefix}"
        thumb_path = bucket_dir / "derived" / "thumb_front.jpg"
        path_candidate: Optional[Path] = None
        if thumb_path.exists():
            path_candidate = thumb_path
        else:
            path_str = row["staged_path"] or row["path"]
            if path_str:
                path_candidate = Path(path_str)
        if path_candidate and bucket_id not in canonical_paths:
            canonical_paths[bucket_id] = path_candidate
        filename = row["original_filename"] or ""
        norm = _normalize(filename)
        if norm:
            stem_map.setdefault(norm, []).append(bucket_id)
        fastfoto = extract_fastfoto_token(filename)
        if fastfoto:
            fastfoto_map[fastfoto] = bucket_id
        img_token = extract_img_token(filename)
        if not img_token and path_candidate:
            img_token = extract_img_token(path_candidate.name)
        register_img_token(img_token, bucket_id)
    cursor.close()

    cursor = conn.execute(
        """
        SELECT bucket_id, key_value
        FROM bucket_join_keys
        WHERE source = ? AND key_type = 'fastfoto'
        """,
        (source,),
    )
    for row in cursor.fetchall():
        fastfoto_map[row["key_value"]] = row["bucket_id"]
    cursor.close()
    cursor = conn.execute(
        """
        SELECT bucket_id, key_value
        FROM bucket_join_keys
        WHERE source = ? AND key_type = 'img_token'
        """,
        (source,),
    )
    for row in cursor.fetchall():
        register_img_token(row["key_value"], row["bucket_id"])
    cursor.close()
    img_token_map: Dict[str, str] = {}
    img_token_conflicts: Dict[str, List[str]] = {}
    for token, buckets in img_token_candidates.items():
        if len(buckets) == 1:
            img_token_map[token] = buckets[0]
        else:
            img_token_conflicts[token] = buckets
    return CanonicalIndex(
        bucket_prefix_map=prefix_map,
        fastfoto_map=fastfoto_map,
        img_token_map=img_token_map,
        img_token_conflicts=img_token_conflicts,
        stem_map=stem_map,
        bucket_prefix_lookup={v: k for k, v in prefix_map.items()},
        canonical_paths=canonical_paths,
    )


@dataclass
class MatchResult:
    status: str
    reason: str
    confidence: str
    bucket_id: Optional[str] = None
    bucket_candidates: Optional[List[str]] = None


def _match_row(row: AIPendingRow, tokens: PendingTokens, index: CanonicalIndex) -> MatchResult:
    # Strategy A: bucket prefix
    for token in tokens.hex_tokens:
        bucket_id = index.bucket_prefix_map.get(token.lower())
        if bucket_id:
            return MatchResult(status="match", reason="bucket_prefix", confidence="HIGH", bucket_id=bucket_id)

    # Strategy B: FastFoto token (from file or stored)
    fastfoto = row.fastfoto_token or tokens.filename_fastfoto
    if fastfoto:
        bucket_id = index.fastfoto_map.get(fastfoto)
        if bucket_id:
            return MatchResult(status="match", reason="fastfoto_token", confidence="HIGH", bucket_id=bucket_id)

    # Strategy C: IMG token
    img_token = (row.img_token or tokens.img_token or "") or None
    if img_token:
        token_norm = img_token.lower()
        conflict_list = index.img_token_conflicts.get(token_norm)
        if conflict_list:
            return MatchResult(
                status="ambiguous",
                reason="img_token_conflict",
                confidence="LOW",
                bucket_candidates=conflict_list,
            )
        bucket_id = index.img_token_map.get(token_norm)
        if bucket_id:
            return MatchResult(status="match", reason="img_token", confidence="HIGH", bucket_id=bucket_id)

    # Strategy D: IMG token normalized fallback via stems
    if tokens.img_token:
        norm = _normalize(tokens.img_token)
        buckets = index.stem_map.get(norm, [])
        unique_buckets = sorted(set(buckets))
        if len(unique_buckets) == 1:
            return MatchResult(
                status="match",
                reason="img_token_stem_match",
                confidence="MEDIUM",
                bucket_id=unique_buckets[0],
            )
        if len(unique_buckets) > 1:
            return MatchResult(
                status="ambiguous",
                reason="img_token_stem_conflict",
                confidence="LOW",
                bucket_candidates=unique_buckets,
            )

    return MatchResult(status="no_signal", reason="no_matching_tokens", confidence="LOW")


def _write_ai_pending_reports(
    reports_dir: Path,
    candidates: List[Tuple[AIPendingRow, str, str, str]],
    ambiguous: List[Tuple[AIPendingRow, List[str], str]],
    no_signal: List[Tuple[AIPendingRow, str]],
) -> None:
    candidate_path = reports_dir / "ai_pending_resolution_candidates.csv"
    ambiguous_path = reports_dir / "ai_pending_ambiguous.csv"
    no_signal_path = reports_dir / "ai_pending_no_signal.csv"

    with candidate_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "ai_sha256",
                "ai_path",
                "pro4k_token",
                "img_token",
                "matched_bucket_prefix",
                "match_reason",
                "confidence",
            ]
        )
        for row, bucket_id, reason, confidence in candidates:
            prefix = bucket_id[:BUCKET_PREFIX_LENGTH]
            tokens = row.parsed_tokens
            writer.writerow(
                [
                    row.sha256,
                    str(row.path),
                    tokens.pro4k_token or "",
                    tokens.img_token or "",
                    prefix,
                    reason,
                    confidence,
                ]
            )

    with ambiguous_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "ai_sha256",
                "ai_path",
                "pro4k_token",
                "img_token",
                "candidate_bucket_prefixes",
                "reason",
            ]
        )
        for row, candidates_list, reason in ambiguous:
            tokens = row.parsed_tokens
            prefixes = [bucket_id[:BUCKET_PREFIX_LENGTH] for bucket_id in candidates_list]
            writer.writerow(
                [
                    row.sha256,
                    str(row.path),
                    tokens.pro4k_token or "",
                    tokens.img_token or "",
                    ";".join(prefixes),
                    reason,
                ]
            )

    with no_signal_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "ai_sha256",
                "ai_path",
                "pro4k_token",
                "img_token",
                "reason",
            ]
        )
        for row, reason in no_signal:
            tokens = row.parsed_tokens
            writer.writerow(
                [
                    row.sha256,
                    str(row.path),
                    tokens.pro4k_token or "",
                    tokens.img_token or "",
                    reason,
                ]
            )


def _write_phash_candidates(
    rows: Sequence[AIPendingRow],
    index: CanonicalIndex,
    reports_dir: Path,
    logger: logging.Logger,
) -> None:
    if not rows:
        return
    canonical_hashes: Dict[str, int] = {}
    for bucket_id, path in index.canonical_paths.items():
        digest = dhash(path)
        if digest is not None:
            canonical_hashes[bucket_id] = digest
    if not canonical_hashes:
        logger.warning("Unable to compute canonical hashes for perceptual comparisons")
        return

    results_path = reports_dir / "ai_pending_phash_candidates.csv"
    with results_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["ai_sha256", "ai_path", "pro4k_token", "img_token", "candidate_bucket_prefix", "distance"]
        )
        for row in rows:
            ai_hash = dhash(row.path)
            if ai_hash is None:
                continue
            best_bucket: Optional[str] = None
            best_distance: Optional[int] = None
            for bucket_id, digest in canonical_hashes.items():
                distance = _hamming_distance(ai_hash, digest)
                if best_distance is None or distance < best_distance:
                    best_distance = distance
                    best_bucket = bucket_id
            if best_bucket is None or best_distance is None:
                continue
            if best_distance > PHASH_THRESHOLD:
                continue
            prefix = best_bucket[:BUCKET_PREFIX_LENGTH]
            tokens = row.parsed_tokens
            writer.writerow(
                [
                    row.sha256,
                    str(row.path),
                    tokens.pro4k_token or "",
                    tokens.img_token or "",
                    prefix,
                    best_distance,
                ]
            )


def parse_tokens(basename: str) -> PendingTokens:
    lower = basename.lower()
    pro_match = PRO4K_RE.search(lower)
    pro_token = pro_match.group(1) if pro_match else None
    img_token = extract_img_token(basename)
    hex_tokens = [token.lower() for token in HEX_RE.findall(lower)]
    filename_fastfoto = extract_fastfoto_token(basename)
    return PendingTokens(
        pro4k_token=pro_token,
        img_token=img_token,
        hex_tokens=hex_tokens,
        filename_fastfoto=filename_fastfoto,
    )


def _write_override_results(path: Path, results: Sequence[OverrideResult]) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "ai_sha256", "bucket_prefix", "status", "message"])
        for result in results:
            writer.writerow([timestamp, result.ai_sha256, result.bucket_prefix, result.status, result.message])


def _normalize(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value)
    return value.strip("_")


def _hamming_distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()
