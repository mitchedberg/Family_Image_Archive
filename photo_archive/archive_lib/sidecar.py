"""Sidecar JSON helpers (placeholder for future bucket metadata management)."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import json
from typing import Any, Dict


@dataclass
class BucketSidecar:
    bucket_id: str
    source: str
    data: Dict[str, Any]

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


def write_sidecar(path: Path, sidecar: BucketSidecar) -> None:
    path.write_text(sidecar.to_json(), encoding="utf-8")
