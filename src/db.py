"""SQLite persistence for deduplication and job tracking."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from src.models import JobStatus, SourceMeta


class Database:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sources (
                    source_id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    title TEXT,
                    views INTEGER DEFAULT 0,
                    published_at TEXT,
                    channel TEXT,
                    platform TEXT DEFAULT 'youtube',
                    status TEXT NOT NULL DEFAULT 'discovered',
                    job_dir TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._ensure_column(conn, "sources", "platform", "TEXT DEFAULT 'youtube'")

    def _ensure_column(
        self, conn: sqlite3.Connection, table: str, column: str, definition: str
    ) -> None:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        names = {row["name"] for row in rows}
        if column not in names:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def should_skip_discovery(self, source_id: str) -> bool:
        """Skip if already rendered or currently in pipeline; retry on failed."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT status FROM sources WHERE source_id = ?",
                (source_id,),
            ).fetchone()
            if not row:
                return False
            return row["status"] != JobStatus.FAILED.value

    def exists(self, source_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM sources WHERE source_id = ?",
                (source_id,),
            ).fetchone()
            return row is not None

    def upsert_source(self, meta: SourceMeta, job_dir: str, status: JobStatus) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO sources (
                    source_id, url, title, views, published_at, channel, platform,
                    status, job_dir, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    url=excluded.url,
                    title=excluded.title,
                    views=excluded.views,
                    published_at=excluded.published_at,
                    channel=excluded.channel,
                    platform=excluded.platform,
                    status=excluded.status,
                    job_dir=excluded.job_dir,
                    updated_at=excluded.updated_at
                """,
                (
                    meta.source_id,
                    meta.url,
                    meta.title,
                    meta.views,
                    meta.published_at,
                    meta.channel,
                    meta.platform,
                    status.value,
                    job_dir,
                    now,
                    now,
                ),
            )

    def update_status(
        self,
        source_id: str,
        status: JobStatus,
        error: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE sources
                SET status = ?, error = ?, updated_at = ?
                WHERE source_id = ?
                """,
                (status.value, error, now, source_id),
            )
