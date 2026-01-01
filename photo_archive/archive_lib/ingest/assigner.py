"""Bucket assignment + sidecar generation."""
from __future__ import annotations

import csv
import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from .. import imaging
from ..config import AppConfig
from ..filename_parser import extract_fastfoto_token, extract_img_token
from ..sidecar import BucketSidecar, write_sidecar

RAW_FRONT = "raw_front"
RAW_BACK = "raw_back"
PROXY_FRONT = "proxy_front"
PROXY_BACK = "proxy_back"
AI_FRONT = "ai_front_v1"
ROLE_ORDER = [RAW_FRONT, RAW_BACK, PROXY_FRONT, PROXY_BACK, AI_FRONT]

TIFF_EXTENSIONS = {".tif", ".tiff"}
JPEG_EXTENSIONS = {".jpg", ".jpeg"}
PNG_EXTENSIONS = {".png"}

FRONT_MARKERS = {"front", "frt", "recto", "obv", "obverse", "a"}
BACK_MARKERS = {"back", "rear", "verso", "rev", "reverse", "b"}
SCAN_TOKENS = {"scan", "scanned", "copy", "edit", "edited", "export", "original"}
QUALITY_TOKENS = {"hires", "highres", "lowres", "web", "print"}
ORDER_TOKENS = {"first", "second", "1", "2", "001", "002"}
TOKEN_SPLIT_RE = re.compile(r"[^a-z0-9]+")
# Import regex patterns from centralized parser module
from ..filename_parser import FASTFOTO_ID_RE, UUID_RE
LUMINANCE_FLIP_THRESHOLD = 0.15
BUCKET_PREFIX_LENGTH = 12


@dataclass
class OverrideRule:
    match: str
    match_type: str  # basename|contains|sha256
    force_group_key: Optional[str] = None
    force_role: Optional[str] = None
    notes: Optional[str] = None

    def applies(self, record: sqlite3.Row) -> bool:
        target = self.match.lower()
        if self.match_type == "sha256":
            return record["sha256"].lower() == target
        filename = record["original_filename"].lower()
        if self.match_type == "basename":
            return filename == target
        if self.match_type == "contains":
            return target in filename
        return False


@dataclass
class FileCandidate:
    row: sqlite3.Row
    path: Path
    group_key: str
    role: Optional[str]
    luminance: Optional[float]
    fastfoto_token: Optional[str] = None
    img_token: Optional[str] = None
    override: Optional[OverrideRule] = None
    needs_review: bool = False
    notes: List[str] = field(default_factory=list)
    is_primary: bool = False

    @property
    def sha256(self) -> str:
        return self.row["sha256"]

    @property
    def original_relpath(self) -> str:
        return self.row["original_relpath"] or ""

    @property
    def original_filename(self) -> str:
        return self.row["original_filename"] or self.path.name

    @property
    def width(self) -> Optional[int]:
        return self.row["width"]

    @property
    def height(self) -> Optional[int]:
        return self.row["height"]


@dataclass
class BucketGroup:
    source: str
    group_key: str
    candidates: List[FileCandidate]
    fastfoto_token: Optional[str] = None
    img_tokens: List[str] = field(default_factory=list)
    needs_review_reasons: List[str] = field(default_factory=list)

    def bucket_id(self) -> Optional[str]:
        canonical = self.canonical_candidate()
        return canonical.sha256 if canonical else None

    def primary_front(self) -> Optional[FileCandidate]:
        fronts = [c for c in self.candidates if c.role == RAW_FRONT]
        return _select_highest_resolution(fronts)

    def primary_proxy(self) -> Optional[FileCandidate]:
        proxies = [c for c in self.candidates if c.role == PROXY_FRONT]
        return _select_highest_resolution(proxies)

    def canonical_candidate(self) -> Optional[FileCandidate]:
        return self.primary_front() or self.primary_proxy()

    def add_review_reason(self, reason: str) -> None:
        if reason not in self.needs_review_reasons:
            self.needs_review_reasons.append(reason)

    def needs_review(self) -> bool:
        return bool(self.needs_review_reasons or any(c.needs_review for c in self.candidates))


@dataclass
class AssignSummary:
    groups_processed: int
    buckets_created: int
    needs_review: int
    ai_orphans: int
    unassigned: int


class Assigner:
    """Create buckets + sidecars based on ingested file metadata."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        cfg: AppConfig,
        *,
        logger: logging.Logger,
        dry_run: bool = False,
    ) -> None:
        self.conn = conn
        self.cfg = cfg
        self.logger = logger
        self.dry_run = dry_run
        self.overrides = load_overrides(cfg.config_dir)
        self._compute_luminance = not dry_run

    def run(
        self,
        *,
        source: str,
        relpath_prefix: Optional[str] = None,
        preview: Optional[int] = None,
    ) -> AssignSummary:
        rows = self._fetch_files(source=source, relpath_prefix=relpath_prefix)
        candidates = [self._build_candidate(row) for row in rows]
        grouped = self._group_candidates(source, candidates)
        ordered_keys = sorted(
            grouped.keys(),
            key=lambda key: (
                grouped[key].fastfoto_token or "",
                key,
            ),
        )
        if preview is not None:
            ordered_keys = ordered_keys[:preview]
        selected_groups = [grouped[key] for key in ordered_keys]
        buckets_created = 0
        needs_review = 0
        ai_orphans: List[FileCandidate] = []
        unassigned: List[FileCandidate] = []
        for group in selected_groups:
            assigned = self._process_group(group)
            if not assigned:
                if self._contains_ai_only(group):
                    self._enqueue_pending(group)
                    ai_orphans.extend(group.candidates)
                else:
                    unassigned.extend(group.candidates)
                continue
            bucket_id = group.bucket_id()
            if not bucket_id:
                unassigned.extend(group.candidates)
                continue
            bucket_dir = self._bucket_dir(bucket_id)
            self._attach_pending_variants(group)
            variants = self._collect_variants(group)
            canonical = group.canonical_candidate()
            sidecar = BucketSidecar(
                bucket_id=bucket_id,
                source=group.source,
                data={
                    "bucket_prefix": bucket_id[:BUCKET_PREFIX_LENGTH],
                    "group_key": group.group_key,
                    "needs_review": group.needs_review(),
                    "needs_review_reasons": group.needs_review_reasons,
                    "variants": variants,
                },
            )
            if canonical:
                metadata = self._fetch_photos_metadata(canonical.sha256)
                if metadata:
                    sidecar.data["photos_asset"] = metadata
            if not self.dry_run:
                self._write_bucket_records(group, bucket_dir, sidecar, variants)
                self._record_join_keys(bucket_id, group)
            buckets_created += 1
            if group.needs_review():
                needs_review += 1
        self._write_reports(selected_groups, ai_orphans, unassigned, source)
        return AssignSummary(
            groups_processed=len(selected_groups),
            buckets_created=buckets_created,
            needs_review=needs_review,
            ai_orphans=len(ai_orphans),
            unassigned=len(unassigned),
        )

    def _fetch_files(
        self,
        *,
        source: str,
        relpath_prefix: Optional[str] = None,
    ) -> List[sqlite3.Row]:
        query = """
            SELECT f.*
            FROM files f
            LEFT JOIN pending_variants pv ON pv.file_sha256 = f.sha256
            WHERE f.source = ? AND pv.file_sha256 IS NULL
        """
        params: List[object] = [source]
        if relpath_prefix:
            query += " AND f.original_relpath LIKE ?"
            params.append(f"{relpath_prefix}%")
        query += " ORDER BY f.original_relpath"
        cursor = self.conn.execute(query, params)
        rows = cursor.fetchall()
        cursor.close()
        return rows

    def _build_candidate(self, row: sqlite3.Row) -> FileCandidate:
        path = Path(row["path"])
        ext = path.suffix.lower()
        override = self._match_override(row)
        group_key = override.force_group_key if override and override.force_group_key else compute_group_key(row["original_filename"])
        role, notes = determine_role(row["original_filename"], ext, override)
        luminance = None
        if ext in TIFF_EXTENSIONS and self._compute_luminance:
            luminance = imaging.mean_luminance(path)
        fastfoto_token = extract_fastfoto_token(row["original_filename"])
        img_token = (
            extract_img_token(row["original_filename"])
            or extract_img_token(row["original_relpath"])
            or extract_img_token(str(path))
        )
        candidate = FileCandidate(
            row=row,
            path=path,
            group_key=group_key,
            role=role,
            luminance=luminance,
            fastfoto_token=fastfoto_token,
            img_token=img_token,
            override=override,
            notes=notes,
        )
        if role is None:
            candidate.needs_review = True
            candidate.notes.append("role_undetermined")
        return candidate

    def _group_candidates(self, source: str, candidates: Sequence[FileCandidate]) -> Dict[str, BucketGroup]:
        groups: Dict[str, BucketGroup] = {}
        negate_by_img_token = source == "negatives"
        for candidate in candidates:
            key = candidate.group_key or "ungrouped"
            if negate_by_img_token and candidate.img_token:
                key = candidate.img_token
            grouped = groups.setdefault(key, BucketGroup(source=source, group_key=key, candidates=[]))
            if candidate.fastfoto_token and not grouped.fastfoto_token:
                grouped.fastfoto_token = candidate.fastfoto_token
            if candidate.img_token and candidate.img_token not in grouped.img_tokens:
                grouped.img_tokens.append(candidate.img_token)
            grouped.candidates.append(candidate)
        return groups

    def _process_group(self, group: BucketGroup) -> bool:
        self._apply_ai_attachment_rules(group)
        self._flag_flip_suspects(group)
        canonical = group.canonical_candidate()
        if not canonical:
            group.add_review_reason("no_canonical_front")
            return False
        canonical.is_primary = True
        for candidate in group.candidates:
            if candidate is canonical:
                continue
            if candidate.role == RAW_BACK and not group.primary_front():
                candidate.needs_review = True
        return True

    def _contains_ai_only(self, group: BucketGroup) -> bool:
        return all(c.role == AI_FRONT for c in group.candidates)

    def _collect_variants(self, group: BucketGroup) -> List[Dict[str, object]]:
        variants = []
        for candidate in group.candidates:
            variants.append(
                {
                    "sha256": candidate.sha256,
                    "role": candidate.role,
                    "is_primary": candidate.is_primary,
                    "path": str(candidate.path),
                    "original_relpath": candidate.original_relpath,
                    "original_filename": candidate.original_filename,
                    "width": candidate.width,
                    "height": candidate.height,
                    "luminance": candidate.luminance,
                    "notes": candidate.notes,
                }
            )
        return variants

    def _write_bucket_records(
        self,
        group: BucketGroup,
        bucket_dir: Path,
        sidecar: BucketSidecar,
        variants: List[Dict[str, object]],
    ) -> None:
        bucket_id = sidecar.bucket_id
        bucket_prefix = bucket_id[:BUCKET_PREFIX_LENGTH]
        bucket_dir.mkdir(parents=True, exist_ok=True)
        write_sidecar(bucket_dir / "sidecar.json", sidecar)
        self.conn.execute(
            """
            INSERT INTO buckets (bucket_id, bucket_prefix, source, preferred_variant)
            VALUES (?, ?, ?, NULL)
            ON CONFLICT(bucket_id) DO UPDATE SET
                bucket_prefix=excluded.bucket_prefix,
                source=excluded.source
            """,
            (bucket_id, bucket_prefix, group.source),
        )
        self.conn.execute("DELETE FROM bucket_files WHERE bucket_id = ?", (bucket_id,))
        for variant in variants:
            self.conn.execute(
                """
                INSERT INTO bucket_files (bucket_id, file_sha256, role, is_primary, notes)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(bucket_id, role, file_sha256) DO UPDATE SET
                    is_primary=excluded.is_primary,
                    notes=excluded.notes
                """,
                (
                    bucket_id,
                    variant["sha256"],
                    variant["role"],
                    int(bool(variant["is_primary"])),
                    json.dumps(variant.get("notes") or []),
                ),
            )
        self.conn.commit()

    def _write_pending_report(self, source: str) -> None:
        pending_path = self.cfg.reports_dir / "pending_variants.csv"
        claimed_path = self.cfg.reports_dir / "pending_with_claimed_keys.csv"
        cursor = self.conn.execute(
            """
            SELECT pv.file_sha256, pv.role, pv.join_key, pv.fastfoto_token, pv.img_token, pv.notes, pv.created_at,
                   f.path, f.original_relpath, f.original_filename
            FROM pending_variants pv
            JOIN files f ON f.sha256 = pv.file_sha256
            WHERE pv.source = ?
            ORDER BY pv.created_at
            """,
            (source,),
        )
        rows = cursor.fetchall()
        cursor.close()
        claimed_rows: List[sqlite3.Row] = []
        with pending_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "file_sha256",
                    "role",
                    "join_key",
                    "fastfoto_token",
                    "img_token",
                    "notes",
                    "created_at",
                    "path",
                    "original_relpath",
                    "original_filename",
                    "join_key_claimed",
                ]
            )
            for row in rows:
                claimed = (
                    self._join_key_claimed(source, "fastfoto", row["fastfoto_token"])
                    or self._join_key_claimed(source, "group_key", row["join_key"])
                    or self._join_key_claimed(source, "img_token", row["img_token"])
                )
                if claimed:
                    claimed_rows.append(row)
                writer.writerow(
                    [
                        row["file_sha256"],
                        row["role"],
                        row["join_key"] or "",
                        row["fastfoto_token"] or "",
                        row["img_token"] or "",
                        row["notes"] or "",
                        row["created_at"],
                        row["path"],
                        row["original_relpath"] or "",
                        row["original_filename"] or "",
                        int(claimed),
                    ]
                )
        with claimed_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "file_sha256",
                    "role",
                    "join_key",
                    "fastfoto_token",
                    "img_token",
                    "notes",
                    "created_at",
                    "path",
                ]
            )
            for row in claimed_rows:
                writer.writerow(
                    [
                        row["file_sha256"],
                        row["role"],
                        row["join_key"] or "",
                        row["fastfoto_token"] or "",
                        row["img_token"] or "",
                        row["notes"] or "",
                        row["created_at"],
                        row["path"],
                    ]
                )

    def _join_key_claimed(self, source: str, key_type: str, key_value: Optional[str]) -> bool:
        if not key_value:
            return False
        cursor = self.conn.execute(
            """
            SELECT 1 FROM bucket_join_keys
            WHERE source = ? AND key_type = ? AND key_value = ?
            """,
            (source, key_type, key_value),
        )
        row = cursor.fetchone()
        cursor.close()
        return bool(row)

    def _enqueue_pending(self, group: BucketGroup) -> None:
        if self.dry_run:
            return
        timestamp = datetime.now(timezone.utc).isoformat()
        for candidate in group.candidates:
            if candidate.role != AI_FRONT:
                continue
            notes = ";".join(candidate.notes)
            fastfoto = candidate.fastfoto_token or group.fastfoto_token
            img_token = candidate.img_token
            self.conn.execute(
                """
                INSERT INTO pending_variants (file_sha256, source, role, join_key, fastfoto_token, img_token, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(file_sha256) DO UPDATE SET
                    join_key=excluded.join_key,
                    fastfoto_token=excluded.fastfoto_token,
                    img_token=excluded.img_token,
                    notes=excluded.notes
                """,
                (
                    candidate.sha256,
                    group.source,
                    candidate.role or "",
                    group.group_key,
                    fastfoto,
                    img_token,
                    notes,
                    timestamp,
                ),
            )
        self.conn.commit()

    def _attach_pending_variants(self, group: BucketGroup) -> None:
        if self.dry_run:
            return
        pending_rows = self._fetch_pending_rows(group)
        if not pending_rows:
            return
        added: List[FileCandidate] = []
        for row in pending_rows:
            file_row = self.conn.execute("SELECT * FROM files WHERE sha256 = ?", (row["file_sha256"],)).fetchone()
            if not file_row:
                continue
            candidate = self._build_candidate(file_row)
            candidate.role = row["role"]
            candidate.notes.append("attached_from_pending")
            added.append(candidate)
        group.candidates.extend(added)
        self.conn.executemany(
            "DELETE FROM pending_variants WHERE file_sha256 = ?",
            [(row["file_sha256"],) for row in pending_rows],
        )
        self.conn.commit()

    def _fetch_pending_rows(self, group: BucketGroup) -> List[sqlite3.Row]:
        conditions: List[str] = []
        params: List[object] = [group.source]
        if group.fastfoto_token:
            conditions.append("fastfoto_token = ?")
            params.append(group.fastfoto_token)
        if group.group_key:
            conditions.append("join_key = ?")
            params.append(group.group_key)
        img_tokens = sorted(
            {
                candidate.img_token
                for candidate in group.candidates
                if candidate.img_token and candidate.role in (RAW_FRONT, PROXY_FRONT)
            }
        )
        if img_tokens:
            placeholders = ", ".join("?" for _ in img_tokens)
            conditions.append(f"img_token IN ({placeholders})")
            params.extend(img_tokens)
        if not conditions:
            return []
        where_clause = " OR ".join(f"({clause})" for clause in conditions)
        query = f"""
            SELECT file_sha256, role
            FROM pending_variants
            WHERE source = ?
              AND ({where_clause})
        """
        cursor = self.conn.execute(query, params)
        rows = cursor.fetchall()
        cursor.close()
        return rows

    def _record_join_keys(self, bucket_id: str, group: BucketGroup) -> None:
        keys: List[tuple[str, str]] = []
        if group.fastfoto_token:
            keys.append(("fastfoto", group.fastfoto_token))
        if group.group_key:
            keys.append(("group_key", group.group_key))
        canonical_tokens = {
            candidate.img_token
            for candidate in group.candidates
            if candidate.role in (RAW_FRONT, PROXY_FRONT) and candidate.img_token
        }
        for token in canonical_tokens:
            keys.append(("img_token", token))
        for key_type, value in keys:
            self.conn.execute(
                """
                INSERT INTO bucket_join_keys (bucket_id, source, key_type, key_value)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(source, key_type, key_value) DO UPDATE SET
                    bucket_id=excluded.bucket_id
                """,
                (bucket_id, group.source, key_type, value),
            )
        self.conn.commit()

    def _fetch_photos_metadata(self, file_sha256: str) -> Optional[Dict[str, object]]:
        try:
            cursor = self.conn.execute(
                "SELECT * FROM photos_assets WHERE file_sha256 = ?", (file_sha256,)
            )
        except sqlite3.OperationalError:
            return None
        row = cursor.fetchone()
        cursor.close()
        if not row:
            return None
        def _split(value: Optional[str]) -> List[str]:
            if not value:
                return []
            return [item for item in value.split(";") if item]
        def _bool(value: Optional[int]) -> Optional[bool]:
            if value is None:
                return None
            return bool(value)
        metadata = {
            "uuid": row["uuid"],
            "original_filename": row["original_filename"],
            "original_filesize": row["original_filesize"],
            "uti_original": row["uti_original"],
            "date": row["date"],
            "date_added": row["date_added"],
            "date_modified": row["date_modified"],
            "hidden": _bool(row["hidden"]),
            "favorite": _bool(row["favorite"]),
            "has_adjustments": _bool(row["has_adjustments"]),
            "adjustment_type": row["adjustment_type"],
            "orientation": row["orientation"],
            "original_orientation": row["original_orientation"],
            "width": row["width"],
            "height": row["height"],
            "original_width": row["original_width"],
            "original_height": row["original_height"],
            "keywords": _split(row["keywords"]),
            "albums": _split(row["albums"]),
            "persons": _split(row["persons"]),
            "face_count": row["face_count"],
            "caption": row["caption"],
            "description": row["description"],
            "title": row["title"],
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "place_name": row["place_name"],
            "import_uuid": row["import_uuid"],
        }
        return metadata

    def _bucket_dir(self, bucket_id: str) -> Path:
        prefix = bucket_id[:BUCKET_PREFIX_LENGTH]
        return self.cfg.buckets_dir / f"bkt_{prefix}"

    def _match_override(self, row: sqlite3.Row) -> Optional[OverrideRule]:
        for rule in self.overrides:
            if rule.applies(row):
                return rule
        return None

    def _apply_ai_attachment_rules(self, group: BucketGroup) -> None:
        for candidate in group.candidates:
            if candidate.role == AI_FRONT and not candidate.group_key.startswith("fastfoto_"):
                candidate.notes.append("ai_no_fastfoto_token")

    def _flag_flip_suspects(self, group: BucketGroup) -> None:
        fronts = [c for c in group.candidates if c.role == RAW_FRONT]
        backs = [c for c in group.candidates if c.role == RAW_BACK]
        if len(fronts) > 1:
            if not any(_contains_front_marker(c.original_filename) for c in fronts):
                group.add_review_reason("ambiguous_multiple_fronts")
        if fronts and backs:
            front = _select_highest_resolution(fronts)
            back = _select_highest_resolution(backs)
            if front and back and front.luminance is not None and back.luminance is not None:
                if front.luminance - back.luminance > LUMINANCE_FLIP_THRESHOLD:
                    group.add_review_reason("luminance_flip_suspect")
                    front.needs_review = True
                    back.needs_review = True

    def _write_reports(
        self,
        groups: Sequence[BucketGroup],
        ai_orphans: Sequence[FileCandidate],
        unassigned: Sequence[FileCandidate],
        source: str,
    ) -> None:
        needs_review_path = self.cfg.reports_dir / "needs_review_buckets.csv"
        with needs_review_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["bucket_id", "group_key", "reasons", "files"])
            for group in groups:
                bucket_id = group.bucket_id()
                if bucket_id and group.needs_review():
                    writer.writerow(
                        [
                            bucket_id,
                            group.group_key,
                            ";".join(group.needs_review_reasons),
                            ";".join(c.original_filename for c in group.candidates),
                        ]
                    )
        ai_orphans_path = self.cfg.reports_dir / "ai_orphans.csv"
        with ai_orphans_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["sha256", "path", "notes"])
            for candidate in ai_orphans:
                writer.writerow([candidate.sha256, str(candidate.path), ";".join(candidate.notes)])
        unassigned_path = self.cfg.reports_dir / "unassigned_files.csv"
        with unassigned_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["sha256", "path", "notes"])
            for candidate in unassigned:
                writer.writerow([candidate.sha256, str(candidate.path), ";".join(candidate.notes)])
        self._write_pending_report(source)


def load_overrides(config_dir: Path) -> List[OverrideRule]:
    path = config_dir / "overrides.csv"
    if not path.exists():
        return []
    rules: List[OverrideRule] = []
    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            match = (row.get("match") or "").strip()
            match_type = (row.get("match_type") or "basename").strip().lower()
            if not match:
                continue
            rules.append(
                OverrideRule(
                    match=match,
                    match_type=match_type,
                    force_group_key=(row.get("force_group_key") or None),
                    force_role=(row.get("force_role") or None),
                    notes=row.get("notes") or None,
                )
            )
    return rules


def compute_group_key(filename: Optional[str]) -> str:
    match = FASTFOTO_ID_RE.search(filename or "")
    if match:
        return f"fastfoto_{match.group(1)}"
    uuid_match = UUID_RE.search(filename or "")
    if uuid_match:
        return uuid_match.group(1).lower().replace("-", "_")
    safe_name = filename or ""
    stem = Path(safe_name).stem.lower()
    tokens = [token for token in TOKEN_SPLIT_RE.split(stem) if token]
    filtered: List[str] = []
    for idx, token in enumerate(tokens):
        if token in FRONT_MARKERS or token in BACK_MARKERS:
            continue
        if token in SCAN_TOKENS or token in QUALITY_TOKENS:
            continue
        if token in ORDER_TOKENS:
            continue
        filtered.append(token)
    if not filtered:
        filtered = tokens or [stem]
    key = "_".join(filtered)
    key = re.sub(r"_+", "_", key).strip("_")
    return key or stem


def determine_role(filename: Optional[str], ext: str, override: Optional[OverrideRule]) -> tuple[Optional[str], List[str]]:
    notes: List[str] = []
    if override and override.force_role:
        return override.force_role, notes
    safe_name = filename or ""
    stem = Path(safe_name).stem.lower()
    if ext in TIFF_EXTENSIONS:
        if _has_back_marker(stem):
            return RAW_BACK, notes
        return RAW_FRONT, notes
    if ext in JPEG_EXTENSIONS:
        if _has_back_marker(stem):
            return PROXY_BACK, notes
        if _is_ai_candidate(stem):
            return AI_FRONT, notes
        return PROXY_FRONT, notes
    if ext in PNG_EXTENSIONS:
        if _is_ai_candidate(stem):
            return AI_FRONT, notes
        return PROXY_FRONT, notes
    return None, notes


def _has_back_marker(stem: str) -> bool:
    if stem.endswith("_b"):
        return True
    tokens = [token for token in TOKEN_SPLIT_RE.split(stem) if token]
    return any(token in BACK_MARKERS for token in tokens)


def _contains_front_marker(filename: str) -> bool:
    lower = filename.lower()
    return any(token in lower for token in FRONT_MARKERS)


def _is_ai_candidate(stem: str) -> bool:
    ai_keywords = {"ai", "enhanced", "restored", "colorize", "remaster", "pro_4k"}
    return any(keyword in stem for keyword in ai_keywords)


def _select_highest_resolution(candidates: Sequence[FileCandidate]) -> Optional[FileCandidate]:
    def resolution(candidate: FileCandidate) -> int:
        width = candidate.width or 0
        height = candidate.height or 0
        return width * height

    best = None
    best_score = -1
    for candidate in candidates:
        score = resolution(candidate)
        if score > best_score:
            best = candidate
            best_score = score
    return best
