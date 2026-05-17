from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from watcharr.clients.arr_client import ArrItem
from watcharr.core.config import default_database_path


SCHEMA_VERSION = 2


@dataclass(frozen=True)
class AvailabilityChange:
    media_key: str
    providers_hash: str = ""
    previous_known: bool = False
    previous_providers: list[str] = field(default_factory=list)
    current_providers: list[str] = field(default_factory=list)
    added_providers: list[str] = field(default_factory=list)
    removed_providers: list[str] = field(default_factory=list)
    changed: bool = False
    notification_created: bool = False

    @property
    def status(self) -> str:
        if not self.previous_known:
            return "NEW" if self.current_providers else "UNCHANGED"
        if self.previous_providers and not self.current_providers:
            return "REMOVED"
        if self.changed:
            return "UPDATED"
        return "UNCHANGED"


class SQLiteStorage:
    def __init__(self, database_path: str):
        self.database_path = database_path
        self.initialize()

    def initialize(self):
        self._ensure_parent_dir()
        with closing(self._connect()) as conn, conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._create_schema(conn)
            self._migrate_schema(conn)
            self._set_schema_version(conn)

    def record_availability(self, kind: str, item: ArrItem, providers: list[str]) -> AvailabilityChange:
        media_key = self.media_key(kind, item.id)
        current_providers = self._normalize_providers(providers)
        current_hash = self._providers_hash(current_providers)
        now = self._now()

        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                """
                SELECT providers_json, providers_hash
                FROM availability_cache
                WHERE media_key = ?
                """,
                (media_key,),
            ).fetchone()

            previous_providers = self._decode_providers(row["providers_json"]) if row else []
            previous_hash = row["providers_hash"] if row else None
            previous_known = row is not None
            changed = previous_known and previous_hash != current_hash
            added = sorted(set(current_providers) - set(previous_providers))
            removed = sorted(set(previous_providers) - set(current_providers))
            notification_created = self._notification_pending(
                conn=conn,
                media_key=media_key,
                event_type="providers_changed",
                providers_hash=current_hash,
            )

            conn.execute(
                """
                INSERT INTO availability_cache (
                    media_key,
                    kind,
                    media_id,
                    title,
                    tmdb_id,
                    tvdb_id,
                    providers_json,
                    providers_hash,
                    first_seen_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(media_key) DO UPDATE SET
                    title = excluded.title,
                    tmdb_id = excluded.tmdb_id,
                    tvdb_id = excluded.tvdb_id,
                    providers_json = excluded.providers_json,
                    providers_hash = excluded.providers_hash,
                    updated_at = excluded.updated_at
                """,
                (
                    media_key,
                    kind,
                    item.id,
                    item.title,
                    item.tmdb_id,
                    item.tvdb_id,
                    json.dumps(current_providers),
                    current_hash,
                    now,
                    now,
                ),
            )

            if changed:
                notification_created = self._ensure_notification_pending(
                    conn=conn,
                    media_key=media_key,
                    kind=kind,
                    title=item.title,
                    event_type="providers_changed",
                    providers_hash=current_hash,
                    providers=current_providers,
                    change_summary={
                        "previous": previous_providers,
                        "current": current_providers,
                        "added": added,
                        "removed": removed,
                    },
                    created_at=now,
                )

            return AvailabilityChange(
                media_key=media_key,
                providers_hash=current_hash,
                previous_known=previous_known,
                previous_providers=previous_providers,
                current_providers=current_providers,
                added_providers=added,
                removed_providers=removed,
                changed=changed,
                notification_created=notification_created,
            )

    def record_scan(
        self,
        *,
        started_at: datetime,
        finished_at: datetime,
        duration_seconds: float,
        country: str,
        dry_run: bool,
        offer_types: list[str],
        missing_count: int,
        processed_count: int,
        skipped_count: int,
        error_count: int,
    ) -> int:
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                """
                INSERT INTO scan_history (
                    started_at,
                    finished_at,
                    duration_seconds,
                    country,
                    dry_run,
                    offer_types_json,
                    missing_count,
                    processed_count,
                    skipped_count,
                    error_count
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self._format_datetime(started_at),
                    self._format_datetime(finished_at),
                    duration_seconds,
                    country,
                    int(dry_run),
                    json.dumps(list(offer_types)),
                    missing_count,
                    processed_count,
                    skipped_count,
                    error_count,
                ),
            )
            return int(cursor.lastrowid)

    def notification_count(self) -> int:
        with closing(self._connect()) as conn:
            return int(conn.execute("SELECT COUNT(*) FROM notification_history").fetchone()[0])

    def mark_notification_sent(self, change: AvailabilityChange) -> bool:
        return self._mark_notification_delivery(change, sent=True, error=None)

    def mark_notification_failed(self, change: AvailabilityChange, error: str) -> bool:
        return self._mark_notification_delivery(change, sent=False, error=error)

    @staticmethod
    def media_key(kind: str, media_id: int) -> str:
        return f"{kind}:{media_id}"

    def _ensure_notification_pending(
        self,
        *,
        conn: sqlite3.Connection,
        media_key: str,
        kind: str,
        title: str,
        event_type: str,
        providers_hash: str,
        providers: list[str],
        change_summary: dict,
        created_at: str,
    ) -> bool:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO notification_history (
                media_key,
                kind,
                title,
                event_type,
                providers_hash,
                providers_json,
                change_summary_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                media_key,
                kind,
                title,
                event_type,
                providers_hash,
                json.dumps(providers),
                json.dumps(change_summary),
                created_at,
            ),
        )
        if cursor.rowcount == 1:
            return True

        return self._notification_pending(
            conn=conn,
            media_key=media_key,
            event_type=event_type,
            providers_hash=providers_hash,
        )

    def _notification_pending(
        self,
        *,
        conn: sqlite3.Connection,
        media_key: str,
        event_type: str,
        providers_hash: str,
    ) -> bool:
        row = conn.execute(
            """
            SELECT sent_at
            FROM notification_history
            WHERE media_key = ?
              AND event_type = ?
              AND providers_hash = ?
            """,
            (media_key, event_type, providers_hash),
        ).fetchone()
        return bool(row and row["sent_at"] is None)

    def _mark_notification_delivery(
        self,
        change: AvailabilityChange,
        *,
        sent: bool,
        error: str | None,
    ) -> bool:
        if not change.providers_hash:
            return False

        sent_at = self._now() if sent else None
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                """
                UPDATE notification_history
                SET sent_at = COALESCE(?, sent_at),
                    last_error = ?,
                    attempt_count = attempt_count + 1
                WHERE media_key = ?
                  AND event_type = 'providers_changed'
                  AND providers_hash = ?
                  AND sent_at IS NULL
                """,
                (sent_at, error, change.media_key, change.providers_hash),
            )
            return cursor.rowcount == 1

    def _create_schema(self, conn: sqlite3.Connection):
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS availability_cache (
                media_key TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                media_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                tmdb_id INTEGER,
                tvdb_id INTEGER,
                providers_json TEXT NOT NULL,
                providers_hash TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_availability_cache_kind
                ON availability_cache(kind);

            CREATE TABLE IF NOT EXISTS notification_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                media_key TEXT NOT NULL,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                event_type TEXT NOT NULL,
                providers_hash TEXT NOT NULL,
                providers_json TEXT NOT NULL,
                change_summary_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                sent_at TEXT,
                last_error TEXT,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                UNIQUE(media_key, event_type, providers_hash)
            );

            CREATE INDEX IF NOT EXISTS idx_notification_history_media_key
                ON notification_history(media_key);

            CREATE TABLE IF NOT EXISTS scan_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL,
                duration_seconds REAL NOT NULL,
                country TEXT NOT NULL,
                dry_run INTEGER NOT NULL,
                offer_types_json TEXT NOT NULL,
                missing_count INTEGER NOT NULL,
                processed_count INTEGER NOT NULL,
                skipped_count INTEGER NOT NULL,
                error_count INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            );
            """
        )

    def _migrate_schema(self, conn: sqlite3.Connection):
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(notification_history)").fetchall()
        }
        if "sent_at" not in columns:
            conn.execute("ALTER TABLE notification_history ADD COLUMN sent_at TEXT")
        if "last_error" not in columns:
            conn.execute("ALTER TABLE notification_history ADD COLUMN last_error TEXT")
        if "attempt_count" not in columns:
            conn.execute(
                "ALTER TABLE notification_history ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0"
            )

    def _set_schema_version(self, conn: sqlite3.Connection):
        conn.execute(
            """
            INSERT OR IGNORE INTO schema_migrations (version, applied_at)
            VALUES (?, ?)
            """,
            (SCHEMA_VERSION, self._now()),
        )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_parent_dir(self):
        if self.database_path == ":memory:":
            return

        parent = Path(self.database_path).expanduser().parent
        if str(parent):
            parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _normalize_providers(providers: list[str]) -> list[str]:
        return sorted({provider for provider in providers if provider})

    @staticmethod
    def _providers_hash(providers: list[str]) -> str:
        payload = json.dumps(providers, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _decode_providers(value: str) -> list[str]:
        decoded = json.loads(value)
        return [str(provider) for provider in decoded]

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _format_datetime(value: datetime) -> str:
        return value.astimezone(UTC).isoformat()


def initialize_storage_from_environment() -> SQLiteStorage:
    database_path = os.getenv("DATABASE_PATH", default_database_path()).strip() or default_database_path()
    return SQLiteStorage(database_path)
