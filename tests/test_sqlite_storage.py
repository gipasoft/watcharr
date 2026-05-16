import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from streaming_checker.clients.arr_client import ArrItem
from streaming_checker.storage.sqlite import SQLiteStorage


class SQLiteStorageTest(unittest.TestCase):
    def test_records_provider_changes_and_deduplicates_notifications(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "streaming-checker.sqlite")
            storage = SQLiteStorage(db_path)
            item = ArrItem(id=10, title="Movie", tmdb_id=100, tvdb_id=None, tags=[], raw={})

            first = storage.record_availability("radarr", item, ["Netflix"])
            same = storage.record_availability("radarr", item, ["Netflix"])
            changed = storage.record_availability("radarr", item, ["Netflix", "Prime Video"])
            repeated_state = storage.record_availability("radarr", item, ["Netflix"])

            self.assertTrue(first.changed)
            self.assertTrue(first.notification_created)
            self.assertFalse(same.changed)
            self.assertFalse(same.notification_created)
            self.assertEqual(changed.added_providers, ["Prime Video"])
            self.assertTrue(changed.notification_created)
            self.assertTrue(repeated_state.changed)
            self.assertFalse(repeated_state.notification_created)
            self.assertEqual(storage.notification_count(), 2)

    def test_initializes_expected_tables(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "streaming-checker.sqlite")
            SQLiteStorage(db_path)

            with closing(sqlite3.connect(db_path)) as conn:
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }

            self.assertIn("availability_cache", tables)
            self.assertIn("notification_history", tables)
            self.assertIn("scan_history", tables)


if __name__ == "__main__":
    unittest.main()
