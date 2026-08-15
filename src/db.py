"""SQLite persistence for deduplication and job tracking."""

from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from src.models import JobStatus, SourceMeta

logger = logging.getLogger(__name__)

IN_PROGRESS = {
    JobStatus.DISCOVERED.value,
    JobStatus.ANALYZED.value,
    JobStatus.REWRITTEN.value,
    JobStatus.VOICED.value,
    JobStatus.RENDERED.value,
}
TERMINAL_OK = {JobStatus.PUBLISHED.value}
DEFAULT_MAX_FAILS = 3
DEFAULT_STALE_HOURS = 6


class Database:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_fails = int(os.getenv("SOURCE_MAX_FAILS", str(DEFAULT_MAX_FAILS)))
        self.stale_hours = float(os.getenv("SOURCE_STALE_HOURS", str(DEFAULT_STALE_HOURS)))
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
            self._ensure_column(conn, "sources", "fail_count", "INTEGER DEFAULT 0")

    def _ensure_column(
        self, conn: sqlite3.Connection, table: str, column: str, definition: str
    ) -> None:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        names = {row["name"] for row in rows}
        if column not in names:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def reclaim_stale(self) -> int:
        """Mark stuck in-progress jobs as failed so they become retryable."""
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=self.stale_hours)
        ).isoformat()
        now = datetime.now(timezone.utc).isoformat()
        placeholders = ",".join("?" for _ in IN_PROGRESS)
        with self._conn() as conn:
            cur = conn.execute(
                f"""
                UPDATE sources
                SET status = ?, error = ?, updated_at = ?,
                    fail_count = COALESCE(fail_count, 0)
                WHERE status IN ({placeholders})
                  AND updated_at < ?
                """,
                (
                    JobStatus.FAILED.value,
                    f"reclaimed stale after {self.stale_hours:g}h",
                    now,
                    *sorted(IN_PROGRESS),
                    cutoff,
                ),
            )
            n = cur.rowcount or 0
        if n:
            logger.warning("Reclaimed %d stale in-progress source(s)", n)
        return n

    def should_skip_discovery(self, source_id: str) -> bool:
        """Skip success / in-progress; allow failed until max_fails."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT status, COALESCE(fail_count, 0) AS fail_count FROM sources WHERE source_id = ?",
                (source_id,),
            ).fetchone()
            if not row:
                return False
            status = row["status"]
            fails = int(row["fail_count"] or 0)
            if status in TERMINAL_OK:
                return True
            if status == JobStatus.FAILED.value:
                return fails >= self.max_fails
            # in-progress or unknown non-failed → skip (unless reclaimed)
            return True

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
                    status, job_dir, fail_count, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
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
            if status == JobStatus.FAILED:
                conn.execute(
                    """
                    UPDATE sources
                    SET status = ?, error = ?, updated_at = ?,
                        fail_count = COALESCE(fail_count, 0) + 1
                    WHERE source_id = ?
                    """,
                    (status.value, error, now, source_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE sources
                    SET status = ?, error = ?, updated_at = ?
                    WHERE source_id = ?
                    """,
                    (status.value, error, now, source_id),
                )
