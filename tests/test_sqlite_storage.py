import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from watcharr.clients.arr_client import ArrItem
from watcharr.storage.sqlite import SQLiteStorage


class SQLiteStorageTest(unittest.TestCase):
    def test_records_provider_changes_and_deduplicates_notifications(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "watcharr.sqlite")
            storage = SQLiteStorage(db_path)
            item = ArrItem(id=10, title="Movie", tmdb_id=100, tvdb_id=None, tags=[], raw={})

            first = storage.record_availability("radarr", item, ["Netflix"])
            same = storage.record_availability("radarr", item, ["Netflix"])
            changed = storage.record_availability("radarr", item, ["Netflix", "Prime Video"])
            repeated_unsent_state = storage.record_availability("radarr", item, ["Netflix", "Prime Video"])

            self.assertFalse(first.changed)
            self.assertFalse(first.notification_created)
            self.assertEqual(first.status, "NEW")
            self.assertFalse(same.changed)
            self.assertFalse(same.notification_created)
            self.assertEqual(same.status, "UNCHANGED")
            self.assertEqual(changed.added_providers, ["Prime Video"])
            self.assertEqual(changed.status, "UPDATED")
            self.assertTrue(changed.notification_created)
            self.assertFalse(repeated_unsent_state.changed)
            self.assertTrue(repeated_unsent_state.notification_created)

            self.assertTrue(storage.mark_notification_sent(changed))
            duplicate = storage.record_availability("radarr", item, ["Netflix", "Prime Video"])
            self.assertFalse(duplicate.changed)
            self.assertFalse(duplicate.notification_created)

            repeated_state = storage.record_availability("radarr", item, ["Netflix"])
            self.assertTrue(repeated_state.changed)
            self.assertTrue(repeated_state.notification_created)
            self.assertEqual(repeated_state.status, "UPDATED")
            self.assertTrue(storage.mark_notification_sent(repeated_state))
            self.assertEqual(storage.notification_count(), 2)

    def test_failed_notification_remains_pending_until_sent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "watcharr.sqlite")
            storage = SQLiteStorage(db_path)
            item = ArrItem(id=10, title="Movie", tmdb_id=100, tvdb_id=None, tags=[], raw={})

            storage.record_availability("radarr", item, ["Netflix"])
            changed = storage.record_availability("radarr", item, ["Netflix", "Prime Video"])
            self.assertTrue(changed.notification_created)

            self.assertTrue(storage.mark_notification_failed(changed, "connection timeout"))
            retry = storage.record_availability("radarr", item, ["Netflix", "Prime Video"])
            self.assertFalse(retry.changed)
            self.assertTrue(retry.notification_created)

            self.assertTrue(storage.mark_notification_sent(retry))
            duplicate = storage.record_availability("radarr", item, ["Netflix", "Prime Video"])
            self.assertFalse(duplicate.notification_created)

    def test_detects_removed_provider_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "watcharr.sqlite")
            storage = SQLiteStorage(db_path)
            item = ArrItem(id=10, title="Movie", tmdb_id=100, tvdb_id=None, tags=[], raw={})

            storage.record_availability("radarr", item, ["Netflix"])
            removed = storage.record_availability("radarr", item, [])

            self.assertTrue(removed.changed)
            self.assertEqual(removed.removed_providers, ["Netflix"])
            self.assertEqual(removed.status, "REMOVED")

    def test_initializes_expected_tables(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "watcharr.sqlite")
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

    def test_migrates_existing_notification_history_table(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "watcharr.sqlite")
            with closing(sqlite3.connect(db_path)) as conn, conn:
                conn.executescript(
                    """
                    CREATE TABLE notification_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        media_key TEXT NOT NULL,
                        kind TEXT NOT NULL,
                        title TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        providers_hash TEXT NOT NULL,
                        providers_json TEXT NOT NULL,
                        change_summary_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        UNIQUE(media_key, event_type, providers_hash)
                    );
                    """
                )

            SQLiteStorage(db_path)

            with closing(sqlite3.connect(db_path)) as conn:
                columns = {
                    row[1]
                    for row in conn.execute("PRAGMA table_info(notification_history)").fetchall()
                }

            self.assertIn("sent_at", columns)
            self.assertIn("last_error", columns)
            self.assertIn("attempt_count", columns)


if __name__ == "__main__":
    unittest.main()
