"""Base classes for CSV and JSON data stores with thread-safe operations."""
from __future__ import annotations

import csv
import json
import threading
from abc import ABC, abstractmethod
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, TypeVar, Generic

T = TypeVar("T")


class BaseCSVStore(ABC, Generic[T]):
    """
    Base class for CSV-based data stores with thread-safe operations.

    This class provides common functionality for stores that persist data
    to CSV files, including:
    - Thread-safe read/write operations using locks
    - Automatic directory creation
    - CSV loading and writing with DictReader/DictWriter
    - Data isolation (all() returns a copy)

    Subclasses must implement:
    - fieldnames: List of CSV column names
    - _parse_row: Convert CSV row dict to data object
    - _row_dict: Convert data object to CSV row dict

    Example:
        class MyStore(BaseCSVStore[MyDataClass]):
            @property
            def fieldnames(self) -> List[str]:
                return ["id", "name", "value"]

            def _parse_row(self, row: Dict[str, str]) -> Optional[MyDataClass]:
                return MyDataClass(id=row["id"], name=row["name"], ...)

            def _row_dict(self, item: MyDataClass) -> Dict[str, Any]:
                return {"id": item.id, "name": item.name, ...}
    """

    def __init__(self, path: Path) -> None:
        """
        Initialize the CSV store.

        Args:
            path: Path to the CSV file
        """
        self.path = path
        self.lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: Dict[Any, T] = {}
        self._load()

    @property
    @abstractmethod
    def fieldnames(self) -> List[str]:
        """
        Return the list of CSV column names.

        This defines the structure of the CSV file and the order of columns.
        Must be implemented by subclasses.

        Returns:
            List of field names for CSV columns
        """
        pass

    @abstractmethod
    def _parse_row(self, row: Dict[str, str]) -> T | None:
        """
        Parse a CSV row dict into a data object.

        Subclasses should implement validation logic and return None
        for invalid rows that should be skipped.

        Args:
            row: Dictionary of CSV row data (keys are fieldnames)

        Returns:
            Parsed data object or None if row should be skipped
        """
        pass

    @abstractmethod
    def _row_dict(self, item: T) -> Dict[str, Any]:
        """
        Convert a data object to a CSV row dictionary.

        Args:
            item: Data object to convert

        Returns:
            Dictionary mapping fieldnames to values
        """
        pass

    @abstractmethod
    def _get_key(self, item: T) -> Any:
        """
        Extract the key for storing the item in _data dict.

        Args:
            item: Data object

        Returns:
            Key to use for this item in the _data dictionary
        """
        pass

    def _load(self) -> None:
        """
        Load data from CSV file.

        Reads the CSV file using DictReader and calls _parse_row for each row.
        Invalid rows (where _parse_row returns None) are skipped.
        """
        if not self.path.exists():
            return
        with self.path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                item = self._parse_row(row)
                if item is not None:
                    key = self._get_key(item)
                    self._data[key] = item

    def _write(self) -> None:
        """
        Write data to CSV file.

        Writes all data using DictWriter. This method should be called
        within a lock context by the subclass.
        """
        with self.path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.fieldnames)
            writer.writeheader()
            for item in self._data.values():
                writer.writerow(self._row_dict(item))

    def all(self) -> Dict[Any, T]:
        """
        Return a copy of all data.

        Returns a shallow copy to prevent external modifications
        from affecting the internal state.

        Returns:
            Dictionary copy of all stored data
        """
        return dict(self._data)


class BaseJSONStore(ABC):
    """
    Base class for JSON-based data stores with thread-safe operations.

    This class provides common functionality for stores that persist data
    to JSON files, including:
    - Thread-safe read/write operations using locks
    - Automatic directory creation
    - Atomic writes using temporary files
    - File modification time tracking for external changes
    - Data isolation (all() returns deepcopy)

    Subclasses can override:
    - _load_data: Custom JSON parsing logic
    - _write_data: Custom JSON serialization logic

    The store automatically detects external file changes and reloads
    when the modification time changes.
    """

    def __init__(self, path: Path) -> None:
        """
        Initialize the JSON store.

        Args:
            path: Path to the JSON file
        """
        self.path = path
        self.lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: Dict[str, Any] = {}
        self._mtime_ns: int = 0
        self._load()

    def _load(self) -> None:
        """
        Load data from JSON file.

        Reads the JSON file and updates the modification time.
        If the file doesn't exist or is empty, initializes with empty data.
        """
        if not self.path.exists():
            self._data = {}
            self._mtime_ns = 0
            return

        # Check if file is empty
        if self.path.stat().st_size == 0:
            self._data = {}
            self._mtime_ns = self._stat_mtime()
            return

        with self.path.open("r", encoding="utf-8") as handle:
            self._data = json.load(handle)

        self._mtime_ns = self._stat_mtime()

    def _stat_mtime(self) -> int:
        """
        Get the file modification time in nanoseconds.

        Returns:
            Modification time in nanoseconds, or 0 if file doesn't exist
        """
        if not self.path.exists():
            return 0
        return self.path.stat().st_mtime_ns

    def _refresh_if_changed(self) -> None:
        """
        Reload data if the file was modified externally.

        Compares current file mtime with cached mtime and reloads
        if they differ. Should be called before read operations.
        """
        current_mtime = self._stat_mtime()
        if current_mtime != self._mtime_ns:
            with self.lock:
                # Double-check after acquiring lock
                current_mtime = self._stat_mtime()
                if current_mtime != self._mtime_ns:
                    self._load()

    def _write(self) -> None:
        """
        Write data to JSON file atomically.

        Uses a temporary file and atomic replace to ensure the file
        is never in a partially written state. Updates the cached mtime.
        This method should be called within a lock context.
        """
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(self._data, handle, indent=2)
        temp_path.replace(self.path)
        self._mtime_ns = self._stat_mtime()

    def all(self) -> Dict[str, Any]:
        """
        Return a deep copy of all data.

        Returns a deep copy to prevent external modifications
        from affecting the internal state. Refreshes from disk
        if the file was modified externally.

        Returns:
            Deep copy of all stored data
        """
        self._refresh_if_changed()
        return deepcopy(self._data)
