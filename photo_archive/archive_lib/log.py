"""Logging helpers."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional


def parse_level(level: str) -> int:
    """Translate a string log level into logging constant."""
    try:
        return getattr(logging, level.upper())
    except AttributeError as exc:
        raise ValueError(f"Unknown log level: {level}") from exc


def setup_logging(level: str = "INFO", log_file: Optional[Path] = None) -> None:
    """Configure root logger for CLI tools."""
    logging.basicConfig(
        level=parse_level(level),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    if log_file:
        handler = logging.FileHandler(log_file)
        handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
        logging.getLogger().addHandler(handler)
