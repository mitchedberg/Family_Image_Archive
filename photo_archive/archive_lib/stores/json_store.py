"""Base class for JSON-backed stores with thread-safe read/write operations."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Dict


class BaseJSONStore:
    """Base class for JSON-backed stores with thread-safe operations.

    Provides:
    - Thread-safe file I/O with atomic writes
    - Versioning and timestamp tracking
    - Automatic parent directory creation
    - Consistent error handling for corrupt files

    Subclasses should:
    - Define VERSION as a class variable
    - Override _init_data() to provide initial data structure
    - Implement domain-specific methods for data access/mutation
    """

    VERSION = 1

    def __init__(self, path: Path) -> None:
        """Initialize store with file path.

        Args:
            path: Path to JSON file for persistence
        """
        self.path = path
        self.lock = threading.Lock()
        self._data: Dict[str, Any] = self._init_data()
        self._load()

    def _init_data(self) -> Dict[str, Any]:
        """Initialize default data structure.

        Subclasses should override this to provide their initial structure.

        Returns:
            Dictionary with initial data structure including version and updated_at
        """
        return {
            "version": self.VERSION,
            "updated_at": int(time.time()),
        }

    def _load(self) -> None:
        """Load data from JSON file if it exists.

        Silently ignores missing or corrupt files, preserving default data.
        Subclasses should override to validate and merge loaded data.
        """
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            # Corrupt file - keep default data
            return

        # Update version if valid
        version = payload.get("version")
        if isinstance(version, int) and version > 0:
            self._data["version"] = version

        # Update timestamp if valid
        updated = payload.get("updated_at")
        if isinstance(updated, (int, float)):
            self._data["updated_at"] = int(updated)

    def _touch_locked(self) -> None:
        """Update version and timestamp. Must be called with lock held."""
        self._data["version"] = self.VERSION
        self._data["updated_at"] = int(time.time())

    def _write_locked(self) -> None:
        """Write data to disk atomically. Must be called with lock held.

        Uses atomic write pattern:
        1. Write to temporary file
        2. Replace original file

        This ensures data integrity even if process crashes during write.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        temp_path.replace(self.path)
