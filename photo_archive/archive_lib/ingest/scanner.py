"""File system scanner for ingest v0."""
from __future__ import annotations

import csv
import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from .. import hashing, imaging, paths
from ..staging import StagedMeta


@dataclass
class ScanRecord:
    root: Path
    path: Path
    sha256: str
    status: str  # "new" or "existing"
    width: int | None
    height: int | None
    error: str | None = None


class Scanner:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        source: str,
        dry_run: bool,
        reports_dir: Path,
        logger: logging.Logger,
    ) -> None:
        self.conn = conn
        self.source = source
        self.dry_run = dry_run
        self.reports_dir = reports_dir
        self.logger = logger

    def scan_roots(
        self,
        roots: Sequence[Path],
        root_labels: Optional[Dict[Path, Optional[str]]] = None,
        staging_map: Optional[Dict[str, StagedMeta]] = None,
    ) -> List[ScanRecord]:
        records: List[ScanRecord] = []
        for root in roots:
            label = root_labels[root] if root_labels and root in root_labels else None
            root_records = self._scan_single_root(root, root_label=label, staging_map=staging_map)
            records.extend(root_records)
            self._write_report_csv(root, root_records)
            self._record_run(root, root_records)
        return records

    def _scan_single_root(
        self,
        root: Path,
        root_label: Optional[str] = None,
        staging_map: Optional[Dict[str, StagedMeta]] = None,
    ) -> List[ScanRecord]:
        self.logger.info("Scanning %s", root)
        records: List[ScanRecord] = []
        for file_path in paths.iter_files(root):
            if not paths.is_candidate_image(file_path):
                continue
            try:
                record = self._process_file(
                    root,
                    file_path,
                    root_label=root_label,
                    staging_map=staging_map,
                )
            except Exception as exc:  # pragma: no cover - protective
                self.logger.exception("Failed to process %s", file_path)
                record = ScanRecord(
                    root=root,
                    path=file_path,
                    sha256="",
                    status="error",
                    width=None,
                    height=None,
                error=str(exc),
            )
            records.append(record)
        self.logger.info(
            "Finished %s | total=%d new=%d existing=%d errors=%d",
            root,
            len(records),
            sum(1 for r in records if r.status == "new"),
            sum(1 for r in records if r.status == "existing"),
            sum(1 for r in records if r.status == "error"),
        )
        return records

    def _process_file(
        self,
        root: Path,
        path: Path,
        root_label: Optional[str] = None,
        staging_map: Optional[Dict[str, StagedMeta]] = None,
    ) -> ScanRecord:
        relpath = paths.relative_to_root(path, root)
        if root_label:
            relpath = relpath or ""
            relpath = f"{root_label}/{relpath}" if relpath else root_label
        stats = path.stat()
        size = stats.st_size
        mtime_epoch = stats.st_mtime
        metadata = imaging.probe_image(path)
        stage_meta = staging_map.get(str(path)) if staging_map else None
        donor_path = stage_meta.donor_path if stage_meta else None
        staged_at = stage_meta.staged_at if stage_meta else None
        staged_path = str(path) if stage_meta else None
        existing_row = self._lookup_existing(
            path=str(path),
            donor_path=donor_path,
            size=size,
            mtime_epoch=mtime_epoch,
            filename=path.name,
        )
        if existing_row and existing_row["sha256"]:
            sha256 = existing_row["sha256"]
            status = "existing"
        else:
            sha256 = hashing.sha256_for_file(path)
            status = "existing" if self._fetch_file(sha256) else "new"
        if not self.dry_run:
            self._upsert_file(
                sha256=sha256,
                path=str(path),
                staged_path=staged_path,
                donor_path=donor_path,
                staged_at=staged_at,
                size=size,
                ext=path.suffix.lower(),
                width=metadata.width,
                height=metadata.height,
                mtime=_isoformat_timestamp(mtime_epoch),
                mtime_epoch=mtime_epoch,
                exif_datetime=metadata.exif_datetime,
                source=self.source,
                original_relpath=relpath,
                original_filename=path.name,
            )
        return ScanRecord(
            root=root,
            path=path,
            sha256=sha256,
            status=status,
            width=metadata.width,
            height=metadata.height,
        )

    def _fetch_file(self, sha256: str) -> sqlite3.Row | None:
        cursor = self.conn.execute("SELECT 1 FROM files WHERE sha256 = ?", (sha256,))
        return cursor.fetchone()

    def _lookup_existing(
        self,
        *,
        path: str,
        donor_path: Optional[str],
        size: int,
        mtime_epoch: float,
        filename: str,
    ) -> sqlite3.Row | None:
        lookups: List[tuple[str, str]] = [
            ("path", path),
            ("staged_path", path),
        ]
        if donor_path:
            lookups.append(("donor_path", donor_path))
        for column, value in lookups:
            cursor = self.conn.execute(
                f"SELECT * FROM files WHERE source = ? AND {column} = ? LIMIT 1",
                (self.source, value),
            )
            row = cursor.fetchone()
            cursor.close()
            if row:
                return row
        cursor = self.conn.execute(
            """
            SELECT * FROM files
            WHERE source = ?
              AND size = ?
              AND original_filename = ?
              AND mtime_epoch IS NOT NULL
              AND ABS(mtime_epoch - ?) < 0.0001
            LIMIT 1
            """,
            (self.source, size, filename, mtime_epoch),
        )
        row = cursor.fetchone()
        cursor.close()
        return row

    def _upsert_file(
        self,
        *,
        sha256: str,
        path: str,
        staged_path: Optional[str],
        donor_path: Optional[str],
        staged_at: Optional[str],
        size: int,
        ext: str,
        width: int | None,
        height: int | None,
        mtime: str,
        mtime_epoch: float,
        exif_datetime: str | None,
        source: str,
        original_relpath: str,
        original_filename: str,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO files (
                sha256, path, staged_path, donor_path, staged_at,
                size, ext, width, height, mtime, mtime_epoch, exif_datetime,
                source, original_relpath, original_filename
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(sha256) DO UPDATE SET
                path=excluded.path,
                staged_path=COALESCE(excluded.staged_path, files.staged_path),
                donor_path=COALESCE(excluded.donor_path, files.donor_path),
                staged_at=COALESCE(excluded.staged_at, files.staged_at),
                size=excluded.size,
                ext=excluded.ext,
                width=excluded.width,
                height=excluded.height,
                mtime=excluded.mtime,
                mtime_epoch=excluded.mtime_epoch,
                exif_datetime=excluded.exif_datetime,
                source=excluded.source,
                original_relpath=excluded.original_relpath,
                original_filename=excluded.original_filename
            ;
            """,
            (
                sha256,
                path,
                staged_path,
                donor_path,
                staged_at,
                size,
                ext,
                width,
                height,
                mtime,
                mtime_epoch,
                exif_datetime,
                source,
                original_relpath,
                original_filename,
            ),
        )
        self.conn.commit()

    def _record_run(self, root: Path, records: Sequence[ScanRecord]) -> None:
        if self.dry_run:
            return
        counts = {
            "total": len(records),
            "new": sum(1 for r in records if r.status == "new"),
            "existing": sum(1 for r in records if r.status == "existing"),
            "errors": sum(1 for r in records if r.status == "error"),
        }
        self.conn.execute(
            """
            INSERT INTO runs (started_at, root, source, dry_run, counts_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                str(root),
                self.source,
                int(self.dry_run),
                json.dumps(counts),
            ),
        )
        self.conn.commit()

    def _write_report_csv(self, root: Path, records: Sequence[ScanRecord]) -> None:
        if not records:
            return
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        report_path = self.reports_dir / f"ingest_{root.name}_{timestamp}.csv"
        with report_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow([
                "root",
                "path",
                "sha256",
                "status",
                "width",
                "height",
                "dry_run",
                "error",
            ])
            for record in records:
                writer.writerow([
                    str(record.root),
                    str(record.path),
                    record.sha256,
                    record.status,
                    record.width or "",
                    record.height or "",
                    int(self.dry_run),
                    record.error or "",
                ])
        self.logger.info("Wrote report %s", report_path)


def _isoformat_timestamp(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
