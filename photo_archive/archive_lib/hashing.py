"""File hashing utilities."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import BinaryIO


DEFAULT_CHUNK_SIZE = 1024 * 1024


def sha256_for_file(path: Path, chunk_size: int = DEFAULT_CHUNK_SIZE) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_for_stream(handle: BinaryIO, chunk_size: int = DEFAULT_CHUNK_SIZE) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: handle.read(chunk_size), b""):
        digest.update(chunk)
    return digest.hexdigest()
