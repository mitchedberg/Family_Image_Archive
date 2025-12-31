"""Path helpers for archive tooling."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable


IMAGE_EXTENSIONS = {".tif", ".tiff", ".jpg", ".jpeg", ".png"}


def is_candidate_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def iter_files(root: Path) -> Iterable[Path]:
    for entry in root.rglob("*"):
        if entry.is_file():
            yield entry


def relative_to_root(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return path.name
