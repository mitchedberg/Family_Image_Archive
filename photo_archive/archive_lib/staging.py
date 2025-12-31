"""SSD staging helpers for donor → SSD copy flow."""
from __future__ import annotations

import csv
import logging
import os
import shutil
import sqlite3
import subprocess
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from . import paths


@dataclass(frozen=True)
class StagedMeta:
    donor_path: Optional[str]
    staged_at: Optional[str]


@dataclass
class StageSummary:
    files_total: int = 0
    files_copied: int = 0
    files_skipped: int = 0
    plan_only: bool = False
    stage_mode: str = "copy"
    stage_root: Optional[str] = None
    manifest_path: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "files_total": self.files_total,
            "files_copied": self.files_copied,
            "files_skipped": self.files_skipped,
            "plan_only": self.plan_only,
            "stage_mode": self.stage_mode,
            "stage_root": self.stage_root,
            "manifest_path": self.manifest_path,
        }


class StageManifestWriter:
    HEADERS = [
        "timestamp",
        "source",
        "donor_root",
        "donor_path",
        "staged_path",
        "size",
        "mtime_epoch",
        "copy_status",
        "sha256_status",
        "stage_mode",
        "staged_at",
    ]

    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle = None
        self._writer = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        file_exists = self.path.exists()
        self._handle = self.path.open("a", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._handle, fieldnames=self.HEADERS)
        if not file_exists:
            self._writer.writeheader()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._handle:
            self._handle.close()
        self._handle = None
        self._writer = None

    def write_row(self, row: Dict[str, object]) -> None:
        if not self._writer:
            raise RuntimeError("StageManifestWriter not initialized")
        safe_row = {key: row.get(key, "") for key in self.HEADERS}
        self._writer.writerow(safe_row)


class StageManager:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        source: str,
        stage_root: Path,
        stage_mode: str,
        manifest_path: Path,
        logger: logging.Logger,
        plan_only: bool = False,
    ) -> None:
        self.conn = conn
        self.source = source
        self.stage_root = stage_root
        self.stage_mode = stage_mode
        self.manifest_path = manifest_path
        self.logger = logger
        self.plan_only = plan_only
        self._timestamp = datetime.now(timezone.utc).isoformat()

    def run(self, root_specs: Sequence[Tuple[Path, str]]) -> Tuple[StageSummary, Dict[str, StagedMeta], List[Tuple[Path, str]]]:
        summary = StageSummary(stage_mode=self.stage_mode, plan_only=self.plan_only, stage_root=str(self.stage_root), manifest_path=str(self.manifest_path))
        staging_map: Dict[str, StagedMeta] = {}
        staged_roots: Dict[str, Path] = {}
        stage_base = self.stage_root / self.source
        stage_base.mkdir(parents=True, exist_ok=True)
        with StageManifestWriter(self.manifest_path) if not self.plan_only else nullcontext() as writer:
            for donor_root, label in root_specs:
                dest_root = stage_base / label
                staged_roots[label] = dest_root
                for donor_path in paths.iter_files(donor_root):
                    if not paths.is_candidate_image(donor_path):
                        continue
                    summary.files_total += 1
                    relpath = paths.relative_to_root(donor_path, donor_root)
                    staged_path = dest_root / relpath
                    decision = self._should_copy(donor_path, staged_path)
                    if decision == "skip":
                        summary.files_skipped += 1
                        if not self.plan_only:
                            writer.write_row(self._manifest_row(donor_root, donor_path, staged_path, "skipped_existing"))
                        continue
                    if self.plan_only:
                        summary.files_copied += 1
                        continue
                    staged_path.parent.mkdir(parents=True, exist_ok=True)
                    self._copy_file(donor_path, staged_path)
                    summary.files_copied += 1
                    meta = StagedMeta(donor_path=str(donor_path), staged_at=self._timestamp)
                    staging_map[str(staged_path)] = meta
                    writer.write_row(self._manifest_row(donor_root, donor_path, staged_path, "copied"))
        staged_specs = [(path, label) for label, path in staged_roots.items()]
        return summary, staging_map, staged_specs

    def _manifest_row(self, donor_root: Path, donor_path: Path, staged_path: Path, status: str) -> Dict[str, object]:
        stats = donor_path.stat()
        return {
            "timestamp": self._timestamp,
            "source": self.source,
            "donor_root": str(donor_root),
            "donor_path": str(donor_path),
            "staged_path": str(staged_path),
            "size": stats.st_size,
            "mtime_epoch": stats.st_mtime,
            "copy_status": status,
            "sha256_status": "pending",
            "stage_mode": self.stage_mode,
            "staged_at": self._timestamp,
        }

    def _copy_file(self, src: Path, dest: Path) -> None:
        if self.stage_mode == "hardlink":
            try:
                if dest.exists():
                    dest.unlink()
                os.link(src, dest)
                return
            except OSError:
                self.logger.warning("Hardlink failed for %s -> %s; falling back to copy", src, dest)
        if self.stage_mode == "rsync":
            cmd = ["rsync", "-t", str(src), str(dest)]
            subprocess.run(cmd, check=True)
        else:
            shutil.copy2(src, dest)
        if dest.stat().st_size != src.stat().st_size:
            raise RuntimeError(f"Staged file size mismatch for {src}")

    def _should_copy(self, donor_path: Path, staged_path: Path) -> str:
        stats = donor_path.stat()
        existing = self._lookup_existing(str(donor_path), str(staged_path))
        if not existing:
            return "copy"
        if existing["sha256"]:
            return "skip"
        size_match = existing["size"] == stats.st_size if existing["size"] is not None else False
        mtime_match = (
            existing["mtime_epoch"] is not None
            and abs(existing["mtime_epoch"] - stats.st_mtime) < 0.0001
        )
        return "skip" if size_match and mtime_match else "copy"

    def _lookup_existing(self, donor_path: str, staged_path: str) -> Optional[sqlite3.Row]:
        cursor = self.conn.execute(
            """
            SELECT * FROM files
            WHERE source = ?
              AND (donor_path = ? OR staged_path = ? OR path = ?)
            LIMIT 1
            """,
            (self.source, donor_path, staged_path, staged_path),
        )
        row = cursor.fetchone()
        cursor.close()
        return row


def load_stage_manifest_map(manifest_path: Path, staged_roots: Sequence[Path]) -> Dict[str, StagedMeta]:
    if not manifest_path or not manifest_path.exists():
        return {}
    prefixes = [str(root.resolve()) for root in staged_roots]
    mapping: Dict[str, StagedMeta] = {}
    with manifest_path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            staged_path = row.get("staged_path")
            if not staged_path:
                continue
            if prefixes and not any(staged_path.startswith(prefix) for prefix in prefixes):
                continue
            donor_path = row.get("donor_path") or None
            staged_at = row.get("staged_at") or row.get("timestamp") or None
            mapping[staged_path] = StagedMeta(donor_path=donor_path, staged_at=staged_at)
    return mapping

