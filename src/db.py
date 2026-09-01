"""SQLite persistence for deduplication and job tracking."""

from __future__ import annotations

import logging
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from src.models import ContentOrder, JobStatus, OrderStatus, SourceMeta

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
ORDER_IN_PROGRESS = {
    OrderStatus.PROCESSING.value,
    OrderStatus.VOICING.value,
    OrderStatus.VISUALS.value,
    OrderStatus.RENDERING.value,
    OrderStatus.PUBLISHING.value,
}


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
        except Exception:
            conn.rollback()
            raise
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    id TEXT PRIMARY KEY,
                    owner_chat_id TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    brief TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    current_stage TEXT NOT NULL DEFAULT 'queued',
                    source_id TEXT NOT NULL DEFAULT '',
                    renderer TEXT NOT NULL DEFAULT 'auto',
                    output_path TEXT NOT NULL DEFAULT '',
                    status_message_id INTEGER,
                    revision_instruction TEXT NOT NULL DEFAULT '',
                    draft_version INTEGER NOT NULL DEFAULT 0,
                    error_code TEXT NOT NULL DEFAULT '',
                    error_user_text TEXT NOT NULL DEFAULT '',
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    started_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_orders_status_created "
                "ON orders(status, created_at)"
            )
            self._ensure_column(conn, "orders", "renderer", "TEXT NOT NULL DEFAULT 'auto'")
            self._ensure_column(conn, "orders", "output_path", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "orders", "idempotency_key", "TEXT NOT NULL DEFAULT ''")
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_idempotency "
                "ON orders(idempotency_key) WHERE idempotency_key != ''"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS telegram_sessions (
                    owner_chat_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL DEFAULT 'idle',
                    active_order_id TEXT NOT NULL DEFAULT '',
                    pending_text TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def _row_to_order(row: sqlite3.Row | None) -> ContentOrder | None:
        if row is None:
            return None
        return ContentOrder.model_validate(dict(row))

    def create_order(
        self,
        owner_chat_id: str,
        topic: str,
        brief: str,
        *,
        renderer: str = "auto",
        idempotency_key: str = "",
    ) -> ContentOrder:
        now = datetime.now(timezone.utc).isoformat()
        order_id = uuid.uuid4().hex[:12]
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO orders (
                    id, owner_chat_id, topic, brief, idempotency_key, renderer, status, current_stage,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order_id,
                    str(owner_chat_id),
                    topic,
                    brief,
                    idempotency_key,
                    renderer,
                    OrderStatus.QUEUED.value,
                    "queued",
                    now,
                    now,
                ),
            )
            if idempotency_key:
                row = conn.execute(
                    "SELECT * FROM orders WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
            else:
                row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        order = self._row_to_order(row)
        assert order is not None
        return order

    def get_order_by_idempotency(self, key: str) -> ContentOrder | None:
        if not key:
            return None
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM orders WHERE idempotency_key = ?", (key,)
            ).fetchone()
        return self._row_to_order(row)

    def get_order(self, order_id: str) -> ContentOrder | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        return self._row_to_order(row)

    def list_orders(self, owner_chat_id: str, limit: int = 10) -> list[ContentOrder]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM orders
                WHERE owner_chat_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (str(owner_chat_id), limit),
            ).fetchall()
        return [self._row_to_order(row) for row in rows if row is not None]

    def claim_next_order(self) -> ContentOrder | None:
        """Atomically claim one queued/resumable order for a pipeline worker."""
        now = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(self.db_path, timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM orders
                WHERE status IN (?, ?, ?, ?)
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (
                    OrderStatus.QUEUED.value,
                    OrderStatus.APPROVED.value,
                    OrderStatus.REVISION_REQUESTED.value,
                    OrderStatus.PUBLISH_REQUESTED.value,
                ),
            ).fetchone()
            if row is None:
                conn.execute("COMMIT")
                return None
            previous = row["status"]
            started_at = row["started_at"] or now
            conn.execute(
                """
                UPDATE orders
                SET status = ?, current_stage = ?, started_at = ?, updated_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    OrderStatus.PROCESSING.value,
                    previous,
                    started_at,
                    now,
                    row["id"],
                    previous,
                ),
            )
            claimed = conn.execute(
                "SELECT * FROM orders WHERE id = ?", (row["id"],)
            ).fetchone()
            conn.execute("COMMIT")
            return self._row_to_order(claimed)
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def has_runnable_orders(self) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM orders
                WHERE status IN (?, ?, ?, ?)
                LIMIT 1
                """,
                (
                    OrderStatus.QUEUED.value,
                    OrderStatus.APPROVED.value,
                    OrderStatus.REVISION_REQUESTED.value,
                    OrderStatus.PUBLISH_REQUESTED.value,
                ),
            ).fetchone()
        return row is not None

    def reclaim_stale_orders(self) -> int:
        """Make interrupted orders visible and retryable after worker crashes."""
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=self.stale_hours)
        ).isoformat()
        now = datetime.now(timezone.utc).isoformat()
        placeholders = ",".join("?" for _ in ORDER_IN_PROGRESS)
        with self._conn() as conn:
            cur = conn.execute(
                f"""
                UPDATE orders
                SET status = ?, current_stage = ?, error_code = ?,
                    error_user_text = ?, updated_at = ?, finished_at = ?
                WHERE status IN ({placeholders}) AND updated_at < ?
                """,
                (
                    OrderStatus.FAILED.value,
                    "failed",
                    "worker_interrupted",
                    "Обработка была прервана. Заказ можно повторить.",
                    now,
                    now,
                    *sorted(ORDER_IN_PROGRESS),
                    cutoff,
                ),
            )
            return cur.rowcount or 0

    def update_order(
        self,
        order_id: str,
        status: OrderStatus,
        *,
        current_stage: str | None = None,
        source_id: str | None = None,
        output_path: str | None = None,
        status_message_id: int | None = None,
        revision_instruction: str | None = None,
        draft_version: int | None = None,
        error_code: str | None = None,
        error_user_text: str | None = None,
        finished: bool = False,
    ) -> ContentOrder | None:
        now = datetime.now(timezone.utc).isoformat()
        fields = ["status = ?", "updated_at = ?"]
        values: list[object] = [status.value, now]
        optional = {
            "current_stage": current_stage,
            "source_id": source_id,
            "output_path": output_path,
            "status_message_id": status_message_id,
            "revision_instruction": revision_instruction,
            "draft_version": draft_version,
            "error_code": error_code,
            "error_user_text": error_user_text,
        }
        for name, value in optional.items():
            if value is not None:
                fields.append(f"{name} = ?")
                values.append(value)
        if finished:
            fields.append("finished_at = ?")
            values.append(now)
        values.append(order_id)
        with self._conn() as conn:
            conn.execute(f"UPDATE orders SET {', '.join(fields)} WHERE id = ?", values)
            row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        return self._row_to_order(row)

    def set_status_message(self, order_id: str, message_id: int) -> None:
        order = self.get_order(order_id)
        if order is not None:
            self.update_order(order_id, order.status, status_message_id=message_id)

    def approve_order(self, order_id: str, owner_chat_id: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                """
                UPDATE orders SET status = ?, current_stage = ?, updated_at = ?
                WHERE id = ? AND owner_chat_id = ? AND status = ?
                """,
                (
                    OrderStatus.APPROVED.value,
                    OrderStatus.APPROVED.value,
                    now,
                    order_id,
                    str(owner_chat_id),
                    OrderStatus.DRAFT_READY.value,
                ),
            )
        return bool(cur.rowcount)

    def request_revision(self, order_id: str, owner_chat_id: str, instruction: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                """
                UPDATE orders
                SET status = ?, current_stage = ?, revision_instruction = ?, updated_at = ?, finished_at = ''
                WHERE id = ? AND owner_chat_id = ? AND status IN (?, ?)
                """,
                (
                    OrderStatus.REVISION_REQUESTED.value,
                    OrderStatus.REVISION_REQUESTED.value,
                    instruction,
                    now,
                    order_id,
                    str(owner_chat_id),
                    OrderStatus.DRAFT_READY.value,
                    OrderStatus.READY.value,
                ),
            )
        return bool(cur.rowcount)

    def request_publish(self, order_id: str, owner_chat_id: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                """
                UPDATE orders SET status = ?, current_stage = ?, updated_at = ?, finished_at = ''
                WHERE id = ? AND owner_chat_id = ? AND status = ?
                  AND output_path != ''
                """,
                (
                    OrderStatus.PUBLISH_REQUESTED.value,
                    OrderStatus.PUBLISH_REQUESTED.value,
                    now,
                    order_id,
                    str(owner_chat_id),
                    OrderStatus.READY.value,
                ),
            )
        return bool(cur.rowcount)

    def cancel_order(self, order_id: str, owner_chat_id: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        cancellable = (
            OrderStatus.QUEUED.value,
            OrderStatus.DRAFT_READY.value,
            OrderStatus.APPROVED.value,
            OrderStatus.REVISION_REQUESTED.value,
            OrderStatus.FAILED.value,
        )
        with self._conn() as conn:
            placeholders = ",".join("?" for _ in cancellable)
            cur = conn.execute(
                f"""
                UPDATE orders
                SET status = ?, current_stage = ?, updated_at = ?, finished_at = ?
                WHERE id = ? AND owner_chat_id = ?
                  AND (
                    status IN ({placeholders})
                    OR (status = ? AND current_stage IN ('queued', 'research', 'rewrite'))
                  )
                """,
                (
                    OrderStatus.CANCELLED.value,
                    OrderStatus.CANCELLED.value,
                    now,
                    now,
                    order_id,
                    str(owner_chat_id),
                    *cancellable,
                    OrderStatus.PROCESSING.value,
                ),
            )
        return bool(cur.rowcount)

    def retry_order(self, order_id: str, owner_chat_id: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                """
                UPDATE orders
                SET status = ?, current_stage = ?, error_code = '', error_user_text = '',
                    retry_count = retry_count + 1, updated_at = ?, finished_at = ''
                WHERE id = ? AND owner_chat_id = ? AND status = ?
                """,
                (
                    OrderStatus.QUEUED.value,
                    OrderStatus.QUEUED.value,
                    now,
                    order_id,
                    str(owner_chat_id),
                    OrderStatus.FAILED.value,
                ),
            )
        return bool(cur.rowcount)

    def get_session(self, owner_chat_id: str) -> dict[str, str]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM telegram_sessions WHERE owner_chat_id = ?",
                (str(owner_chat_id),),
            ).fetchone()
        if row is None:
            return {"state": "idle", "active_order_id": "", "pending_text": ""}
        return dict(row)

    def set_session(
        self,
        owner_chat_id: str,
        state: str,
        *,
        active_order_id: str = "",
        pending_text: str = "",
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO telegram_sessions (
                    owner_chat_id, state, active_order_id, pending_text, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(owner_chat_id) DO UPDATE SET
                    state=excluded.state,
                    active_order_id=excluded.active_order_id,
                    pending_text=excluded.pending_text,
                    updated_at=excluded.updated_at
                """,
                (str(owner_chat_id), state, active_order_id, pending_text, now),
            )

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

    def list_retryable_failed(self, limit: int = 10) -> list[SourceMeta]:
        """Return failed sources that are still under the fail-count cap."""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT source_id, url, title, views, published_at, channel, platform,
                       COALESCE(fail_count, 0) AS fail_count
                FROM sources
                WHERE status = ?
                  AND COALESCE(fail_count, 0) < ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (JobStatus.FAILED.value, self.max_fails, limit),
            ).fetchall()
        out: list[SourceMeta] = []
        for row in rows:
            # Prefer retries ahead of fresh low-score noise
            score = 5e8 - float(row["fail_count"] or 0) * 1e6
            out.append(
                SourceMeta(
                    source_id=row["source_id"],
                    url=row["url"] or "",
                    title=row["title"] or row["source_id"],
                    views=int(row["views"] or 0),
                    published_at=row["published_at"] or "",
                    channel=row["channel"] or "",
                    platform=row["platform"] or "youtube",
                    query="db_retry",
                    score=score,
                )
            )
        if out:
            logger.info("Queued %d retryable failed source(s) from DB", len(out))
        return out

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
