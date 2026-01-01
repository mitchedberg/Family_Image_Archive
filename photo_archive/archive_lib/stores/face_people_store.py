"""Store for managing face people metadata (pins, groups, ignored labels)."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Dict

from .json_store import BaseJSONStore


class FacePeopleStore(BaseJSONStore):
    """Simple JSON-backed metadata for pins/groups/ignored labels.

    Manages per-label metadata including:
    - Pinned status: Whether a label should appear at top of lists
    - Group: Optional group/category for organizing labels
    - Ignored status: Whether a label should be hidden from UI

    Thread-safe with atomic file writes.
    """

    VERSION = 1

    def _init_data(self) -> Dict[str, object]:
        """Initialize data structure with labels and groups."""
        return {
            "version": self.VERSION,
            "updated_at": int(time.time()),
            "labels": {},
            "groups": {},
        }

    def _load(self) -> None:
        """Load and validate labels/groups from JSON file."""
        if not self.path.exists():
            return
        try:
            import json
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}

        # Validate and load labels
        labels = payload.get("labels")
        self._data["labels"] = labels if isinstance(labels, dict) else {}

        # Validate and load groups
        groups = payload.get("groups")
        self._data["groups"] = groups if isinstance(groups, dict) else {}

        # Update version if valid
        version = payload.get("version")
        if isinstance(version, int) and version > 0:
            self._data["version"] = version

        # Update timestamp if valid
        updated = payload.get("updated_at")
        if isinstance(updated, (int, float)):
            self._data["updated_at"] = int(updated)

    def label_metadata(self, label: str) -> Dict[str, object]:
        """Get metadata for a label.

        Args:
            label: Label name to query

        Returns:
            Dictionary with pinned (bool), group (str), and ignored (bool) keys
        """
        entry = self._data.get("labels", {}).get(label)
        if not isinstance(entry, dict):
            return {"pinned": False, "group": "", "ignored": False}
        return {
            "pinned": bool(entry.get("pinned")),
            "group": str(entry.get("group") or ""),
            "ignored": bool(entry.get("ignored")),
        }

    def all_labels(self) -> Dict[str, Dict[str, object]]:
        """Get all label metadata.

        Returns:
            Dictionary mapping label names to their metadata
        """
        labels = self._data.get("labels")
        if isinstance(labels, dict):
            return dict(labels)
        return {}

    def set_pinned(self, label: str, pinned: bool) -> Dict[str, object]:
        """Set pinned status for a label.

        Args:
            label: Label name
            pinned: Whether label should be pinned

        Returns:
            Updated metadata for the label
        """
        return self._update_label(label, lambda entry: entry.__setitem__("pinned", bool(pinned)))

    def set_group(self, label: str, group: str) -> Dict[str, object]:
        """Set group for a label.

        Args:
            label: Label name
            group: Group name (empty string to remove group)

        Returns:
            Updated metadata for the label
        """
        clean_group = group.strip()
        if not clean_group:
            def mutator(entry: Dict[str, object]) -> None:
                entry.pop("group", None)
        else:
            def mutator(entry: Dict[str, object]) -> None:
                entry["group"] = clean_group
        return self._update_label(label, mutator)

    def set_ignored(self, label: str, ignored: bool) -> Dict[str, object]:
        """Set ignored status for a label.

        Args:
            label: Label name
            ignored: Whether label should be ignored

        Returns:
            Updated metadata for the label
        """
        return self._update_label(label, lambda entry: entry.__setitem__("ignored", bool(ignored)))

    def _update_label(self, label: str, mutator: Callable[[Dict[str, object]], None]) -> Dict[str, object]:
        """Update a label's metadata atomically.

        Args:
            label: Label name
            mutator: Function that modifies the label's entry dict

        Returns:
            Updated metadata for the label

        Raises:
            ValueError: If label is empty
        """
        clean_label = label.strip()
        if not clean_label:
            raise ValueError("label is required")

        with self.lock:
            labels = self._data.setdefault("labels", {})
            entry = labels.get(clean_label)
            if not isinstance(entry, dict):
                entry = {}
                labels[clean_label] = entry
            mutator(entry)
            self._cleanup_label(clean_label)
            self._touch_locked()
            self._write_locked()
            return self.label_metadata(clean_label)

    def _cleanup_label(self, label: str) -> None:
        """Remove label entry if it has no meaningful data.

        Args:
            label: Label to potentially clean up
        """
        entry = self._data.get("labels", {}).get(label)
        if not isinstance(entry, dict):
            self._data.get("labels", {}).pop(label, None)
            return
        if not entry.get("pinned") and not entry.get("ignored") and not entry.get("group"):
            self._data.get("labels", {}).pop(label, None)
