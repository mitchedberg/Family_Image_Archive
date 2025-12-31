"""Small helpers for label normalization/sanitization."""
from __future__ import annotations


def normalize_label(value: str) -> str:
    """Return a stable key for a label (strip + casefold)."""
    if value is None:
        return ""
    return value.strip().casefold()

