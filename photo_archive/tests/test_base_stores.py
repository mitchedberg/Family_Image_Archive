"""Unit tests for base store classes."""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from photo_archive.archive_lib.base_stores import BaseCSVStore, BaseJSONStore


@dataclass
class TestItem:
    """Simple test data class for CSV store tests."""
    id: str
    name: str
    value: int


class TestCSVStore(BaseCSVStore[TestItem]):
    """Concrete implementation of BaseCSVStore for testing."""

    @property
    def fieldnames(self) -> List[str]:
        return ["id", "name", "value"]

    def _parse_row(self, row: Dict[str, str]) -> TestItem | None:
        item_id = row.get("id", "").strip()
        name = row.get("name", "").strip()
        value_str = row.get("value", "").strip()

        if not item_id or not name:
            return None

        try:
            value = int(value_str)
        except ValueError:
            return None

        return TestItem(id=item_id, name=name, value=value)

    def _row_dict(self, item: TestItem) -> Dict[str, Any]:
        return {
            "id": item.id,
            "name": item.name,
            "value": str(item.value),
        }

    def _get_key(self, item: TestItem) -> str:
        return item.id

    def add(self, item: TestItem) -> None:
        """Add an item to the store."""
        with self.lock:
            self._data[item.id] = item
            self._write()

    def remove(self, item_id: str) -> None:
        """Remove an item from the store."""
        with self.lock:
            if item_id in self._data:
                del self._data[item_id]
                self._write()


class TestJSONStore(BaseJSONStore):
    """Concrete implementation of BaseJSONStore for testing."""

    def set_value(self, key: str, value: Any) -> None:
        """Set a value in the store."""
        with self.lock:
            self._data[key] = value
            self._write()

    def get_value(self, key: str, default: Any = None) -> Any:
        """Get a value from the store."""
        self._refresh_if_changed()
        return self._data.get(key, default)

    def remove_value(self, key: str) -> None:
        """Remove a value from the store."""
        with self.lock:
            if key in self._data:
                del self._data[key]
                self._write()


class BaseCSVStoreTests(unittest.TestCase):
    """Tests for BaseCSVStore functionality."""

    def setUp(self) -> None:
        """Create a temporary file for each test."""
        self.temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False)
        self.temp_path = Path(self.temp_file.name)
        self.temp_file.close()
        self.store = TestCSVStore(self.temp_path)

    def tearDown(self) -> None:
        """Clean up temporary file."""
        if self.temp_path.exists():
            self.temp_path.unlink()

    def test_init_creates_empty_store(self) -> None:
        """Test that initialization creates an empty store."""
        self.assertEqual(len(self.store.all()), 0)

    def test_add_item(self) -> None:
        """Test adding an item to the store."""
        item = TestItem(id="1", name="test", value=42)
        self.store.add(item)
        all_items = self.store.all()
        self.assertIn("1", all_items)
        self.assertEqual(all_items["1"].name, "test")
        self.assertEqual(all_items["1"].value, 42)

    def test_all_returns_copy(self) -> None:
        """Test that all() returns a copy, not the original data."""
        item = TestItem(id="1", name="test", value=42)
        self.store.add(item)

        # Get the data
        data1 = self.store.all()
        data2 = self.store.all()

        # Modify one copy
        data1["1"] = TestItem(id="1", name="modified", value=99)

        # Verify the other copy is unchanged
        self.assertEqual(data2["1"].name, "test")
        self.assertEqual(data2["1"].value, 42)

        # Verify the store itself is unchanged
        data3 = self.store.all()
        self.assertEqual(data3["1"].name, "test")
        self.assertEqual(data3["1"].value, 42)

    def test_persistence(self) -> None:
        """Test that data persists across store instances."""
        item1 = TestItem(id="1", name="first", value=10)
        item2 = TestItem(id="2", name="second", value=20)
        self.store.add(item1)
        self.store.add(item2)

        # Create a new store instance with the same file
        new_store = TestCSVStore(self.temp_path)
        all_items = new_store.all()

        self.assertEqual(len(all_items), 2)
        self.assertEqual(all_items["1"].name, "first")
        self.assertEqual(all_items["2"].name, "second")

    def test_remove_item(self) -> None:
        """Test removing an item from the store."""
        item = TestItem(id="1", name="test", value=42)
        self.store.add(item)
        self.assertEqual(len(self.store.all()), 1)

        self.store.remove("1")
        self.assertEqual(len(self.store.all()), 0)

    def test_parse_row_validation(self) -> None:
        """Test that invalid rows are skipped during load."""
        # Write a CSV with some invalid rows
        with self.temp_path.open("w", encoding="utf-8") as f:
            f.write("id,name,value\n")
            f.write("1,valid,42\n")
            f.write(",missing_id,10\n")  # Invalid: missing id
            f.write("3,,20\n")  # Invalid: missing name
            f.write("4,another,not_a_number\n")  # Invalid: bad value
            f.write("5,good,100\n")

        # Load the store
        store = TestCSVStore(self.temp_path)
        all_items = store.all()

        # Only valid rows should be loaded
        self.assertEqual(len(all_items), 2)
        self.assertIn("1", all_items)
        self.assertIn("5", all_items)

    def test_thread_safety(self) -> None:
        """Test concurrent access with multiple threads."""
        num_threads = 10
        items_per_thread = 10

        def add_items(thread_id: int) -> None:
            for i in range(items_per_thread):
                item_id = f"{thread_id}_{i}"
                item = TestItem(id=item_id, name=f"thread{thread_id}", value=i)
                self.store.add(item)

        threads = []
        for t in range(num_threads):
            thread = threading.Thread(target=add_items, args=(t,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # Verify all items were added
        all_items = self.store.all()
        self.assertEqual(len(all_items), num_threads * items_per_thread)


class BaseJSONStoreTests(unittest.TestCase):
    """Tests for BaseJSONStore functionality."""

    def setUp(self) -> None:
        """Create a temporary file for each test."""
        self.temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        self.temp_path = Path(self.temp_file.name)
        self.temp_file.close()
        self.store = TestJSONStore(self.temp_path)

    def tearDown(self) -> None:
        """Clean up temporary file."""
        if self.temp_path.exists():
            self.temp_path.unlink()
        # Clean up any .tmp files
        tmp_path = self.temp_path.with_suffix(self.temp_path.suffix + ".tmp")
        if tmp_path.exists():
            tmp_path.unlink()

    def test_init_creates_empty_store(self) -> None:
        """Test that initialization creates an empty store."""
        self.assertEqual(len(self.store.all()), 0)

    def test_set_and_get_value(self) -> None:
        """Test setting and getting values."""
        self.store.set_value("key1", "value1")
        self.store.set_value("key2", 42)
        self.store.set_value("key3", {"nested": "dict"})

        self.assertEqual(self.store.get_value("key1"), "value1")
        self.assertEqual(self.store.get_value("key2"), 42)
        self.assertEqual(self.store.get_value("key3"), {"nested": "dict"})

    def test_all_returns_deepcopy(self) -> None:
        """Test that all() returns a deep copy."""
        self.store.set_value("key1", {"nested": {"value": 42}})

        # Get the data
        data1 = self.store.all()
        data2 = self.store.all()

        # Modify nested value in one copy
        data1["key1"]["nested"]["value"] = 99

        # Verify the other copy is unchanged
        self.assertEqual(data2["key1"]["nested"]["value"], 42)

        # Verify the store itself is unchanged
        data3 = self.store.all()
        self.assertEqual(data3["key1"]["nested"]["value"], 42)

    def test_persistence(self) -> None:
        """Test that data persists across store instances."""
        self.store.set_value("key1", "value1")
        self.store.set_value("key2", [1, 2, 3])

        # Create a new store instance with the same file
        new_store = TestJSONStore(self.temp_path)

        self.assertEqual(new_store.get_value("key1"), "value1")
        self.assertEqual(new_store.get_value("key2"), [1, 2, 3])

    def test_remove_value(self) -> None:
        """Test removing a value from the store."""
        self.store.set_value("key1", "value1")
        self.assertEqual(len(self.store.all()), 1)

        self.store.remove_value("key1")
        self.assertEqual(len(self.store.all()), 0)

    def test_file_modification_detection(self) -> None:
        """Test that external file changes are detected."""
        self.store.set_value("key1", "original")

        # Modify the file externally
        with self.temp_path.open("w", encoding="utf-8") as f:
            json.dump({"key1": "modified", "key2": "new"}, f, indent=2)

        # The store should detect the change and reload
        self.assertEqual(self.store.get_value("key1"), "modified")
        self.assertEqual(self.store.get_value("key2"), "new")

    def test_atomic_write(self) -> None:
        """Test that writes are atomic (use temp file)."""
        self.store.set_value("key1", "value1")

        # Verify that temp file doesn't exist after write
        tmp_path = self.temp_path.with_suffix(self.temp_path.suffix + ".tmp")
        self.assertFalse(tmp_path.exists())

        # Verify the actual file exists and has correct content
        self.assertTrue(self.temp_path.exists())
        with self.temp_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["key1"], "value1")

    def test_thread_safety(self) -> None:
        """Test concurrent access with multiple threads."""
        num_threads = 10
        items_per_thread = 10

        def set_values(thread_id: int) -> None:
            for i in range(items_per_thread):
                key = f"thread{thread_id}_item{i}"
                self.store.set_value(key, i)

        threads = []
        for t in range(num_threads):
            thread = threading.Thread(target=set_values, args=(t,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # Verify all items were added
        all_data = self.store.all()
        self.assertEqual(len(all_data), num_threads * items_per_thread)


if __name__ == "__main__":
    unittest.main()
