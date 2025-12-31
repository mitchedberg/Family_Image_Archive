import tempfile
import unittest
from pathlib import Path

from archive_lib.face_tags import FaceTagStore
from archive_lib.face_votes import FaceVoteStore
from archive_lib.face_ignores import FaceIgnoreStore


class FaceTagStoreMergeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tags_path = Path(self.tmpdir.name) / "face_tags.csv"
        self.store = FaceTagStore(self.tags_path)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_merge_labels_moves_faces_to_existing_target(self) -> None:
        self.store.update("face_a", "bucket_a", 0, "Alice")
        self.store.update("face_b", "bucket_b", 1, "Beth")
        changed = self.store.merge_labels("Beth", "Alice")
        self.assertEqual(changed, 1)
        tags = self.store.all()
        self.assertEqual(tags["face_b"].label, "Alice")
        self.assertIn("face_a", tags)
        self.assertEqual(tags["face_a"].label, "Alice")

    def test_merge_labels_allows_new_target(self) -> None:
        self.store.update("face_a", "bucket_a", 0, "Alice")
        changed = self.store.merge_labels("Alice", "Carol")
        self.assertEqual(changed, 1)
        tags = self.store.all()
        self.assertEqual(tags["face_a"].label, "Carol")


class FaceVoteStoreMergeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.votes_path = Path(self.tmpdir.name) / "face_votes.csv"
        self.store = FaceVoteStore(self.votes_path)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_merge_votes_prefers_accept(self) -> None:
        self.store.record("face_a", "Alice", "reject")
        self.store.record("face_a", "Beth", "accept")
        changed = self.store.merge_labels("Beth", "Alice")
        self.assertEqual(changed, 1)
        votes = self.store.all()
        merged = votes[("face_a", "Alice")]
        self.assertEqual(merged.verdict, "accept")

    def test_merge_votes_creates_new_target(self) -> None:
        self.store.record("face_b", "Beth", "reject")
        changed = self.store.merge_labels("Beth", "Carol")
        self.assertEqual(changed, 1)
        votes = self.store.all()
        self.assertIn(("face_b", "Carol"), votes)
        self.assertEqual(votes[("face_b", "Carol")].verdict, "reject")


class FaceVoteStoreClearTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.votes_path = Path(self.tmpdir.name) / "face_votes.csv"
        self.store = FaceVoteStore(self.votes_path)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_clear_removes_existing_vote(self) -> None:
        self.store.record("face_a", "Alice", "accept")
        cleared = self.store.clear("face_a", "Alice")
        self.assertTrue(cleared)
        self.assertNotIn(("face_a", "Alice"), self.store.all())

    def test_clear_handles_missing_vote(self) -> None:
        cleared = self.store.clear("face_x", "Missing")
        self.assertFalse(cleared)


class FaceIgnoreStoreRemoveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tmpdir.name) / "face_ignores.csv"
        self.store = FaceIgnoreStore(self.path)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_remove_deletes_existing_ignore(self) -> None:
        self.store.add("face_a", "test")
        removed = self.store.remove("face_a")
        self.assertTrue(removed)
        self.assertNotIn("face_a", self.store.all())

    def test_remove_missing_ignore(self) -> None:
        removed = self.store.remove("face_missing")
        self.assertFalse(removed)


if __name__ == "__main__":
    unittest.main()
