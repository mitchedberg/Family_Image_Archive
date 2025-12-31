"""Configuration helpers for locating important paths."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class AppConfig:
    repo_root: Path
    staging_root: Path
    db_path: Path
    reports_dir: Path
    buckets_dir: Path
    config_dir: Path
    strip_subdir: Optional[Path] = None


def detect_repo_root() -> Path:
    """Return the root of the photo_archive package."""
    return Path(__file__).resolve().parents[1]


def detect_staging_root(repo_root: Path) -> Path:
    """Our staging root is the parent directory that holds 01_INBOX/etc."""
    return repo_root.parent


def default_db_path(staging_root: Path) -> Path:
    return staging_root / "02_WORKING_BUCKETS" / "db" / "archive.sqlite"


def default_reports_dir(staging_root: Path) -> Path:
    path = staging_root / "02_WORKING_BUCKETS" / "reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_buckets_dir(staging_root: Path) -> Path:
    path = staging_root / "02_WORKING_BUCKETS" / "buckets"
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_config_dir(staging_root: Path) -> Path:
    path = staging_root / "02_WORKING_BUCKETS" / "config"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_config(db_path: Optional[Path] = None) -> AppConfig:
    repo_root = detect_repo_root()
    staging_root = detect_staging_root(repo_root)
    resolved_db_path = Path(db_path) if db_path else default_db_path(staging_root)
    resolved_db_path.parent.mkdir(parents=True, exist_ok=True)
    reports_dir = default_reports_dir(staging_root)
    buckets_dir = default_buckets_dir(staging_root)
    config_dir = default_config_dir(staging_root)
    strip_subdir = staging_root / "02_WORKING_BUCKETS" / "strip_originals"
    strip_subdir.mkdir(parents=True, exist_ok=True)
    return AppConfig(
        repo_root=repo_root,
        staging_root=staging_root,
        db_path=resolved_db_path,
        reports_dir=reports_dir,
        buckets_dir=buckets_dir,
        config_dir=config_dir,
        strip_subdir=strip_subdir,
    )
