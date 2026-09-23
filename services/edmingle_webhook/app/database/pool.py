from __future__ import annotations

import logging
import socket
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC

import psycopg2.extras
from psycopg2 import pool
from psycopg2.extras import Json

from app.config.settings import Settings
from app.models.event import WebhookEvent

psycopg2.extras.register_uuid()

logger = logging.getLogger("webhook.database")

_PIPELINE_NAME = "webhook_ingestion"
_HOST_NAME = socket.gethostname()


@dataclass(frozen=True)
class InsertResult:
    inserted: bool
    duplicate: bool
    webhook_event_id: int | None


class DatabasePool:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pool: pool.ThreadedConnectionPool | None = None

    def open(self) -> None:
        if self._pool is not None:
            return
        self._pool = pool.ThreadedConnectionPool(
            minconn=self._settings.db_pool_min_connections,
            maxconn=self._settings.db_pool_max_connections,
            dbname=self._settings.db_name,
            user=self._settings.db_user,
            password=self._settings.db_password,
            host=self._settings.db_host,
            port=self._settings.db_port,
            connect_timeout=self._settings.db_connect_timeout_seconds,
            options=f"-c statement_timeout={self._settings.db_statement_timeout_ms}",
        )

    def close(self) -> None:
        if self._pool is not None:
            self._pool.closeall()
            self._pool = None

    def health_check(self) -> bool:
        try:
            with self.connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    return cursor.fetchone()[0] == 1
        except Exception:
            logger.exception("database health check failed")
            return False

    def insert_event(self, event: WebhookEvent) -> InsertResult:
        last_error: Exception | None = None
        for attempt in range(1, self._settings.db_retry_attempts + 1):
            try:
                return self._insert_event_once(event)
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "database insert attempt failed", extra={"attempt": attempt, "request_id": event.request_id}
                )
                if attempt < self._settings.db_retry_attempts:
                    time.sleep(self._settings.db_retry_backoff_ms / 1000)
        raise RuntimeError("database insert failed after retries") from last_error

    def _insert_event_once(self, event: WebhookEvent) -> InsertResult:
        with self.connection() as conn:
            try:
                with conn.cursor() as cursor:
                    if self._settings.dedup_enabled:
                        cursor.execute(
                            """
                            INSERT INTO public.webhook_event_dedup (dedup_key, event_id, first_seen_at, source)
                            VALUES (%s, %s, %s, %s)
                            ON CONFLICT (dedup_key) DO NOTHING
                            RETURNING dedup_key
                            """,
                            (event.dedup_key, event.event_id, _db_timestamp(event), event.source),
                        )
                        if cursor.fetchone() is None:
                            conn.rollback()
                            return InsertResult(inserted=False, duplicate=True, webhook_event_id=None)

                    # A live webhook event has no natural "run" boundary the way a
                    # scheduled collector pull does -- it's one atomic unit of
                    # work, known-complete the moment this transaction commits.
                    # So the pipeline_run row is written already-SUCCESS/finished,
                    # in the same transaction as the Bronze row it accounts for,
                    # rather than a separate start()-then-finish() pair (which
                    # only earns its keep for genuinely long-running work).
                    # legacy_source_database/legacy_source_id stay NULL here --
                    # those are only set by the historical backfill (see
                    # scripts/backfill_bronze_webhook_events.py), never by live
                    # inserts.
                    run_id = uuid.uuid4()
                    cursor.execute(
                        """
                        INSERT INTO audit.pipeline_runs (
                            id, pipeline_name, run_type, status,
                            started_at, finished_at, rows_read, rows_written, host_name
                        ) VALUES (%s, %s, 'streaming', 'SUCCESS', now(), now(), 1, 1, %s)
                        """,
                        (run_id, _PIPELINE_NAME, _HOST_NAME),
                    )
                    cursor.execute(
                        """
                        INSERT INTO bronze.webhook_events (pipeline_run_id, source, received_at, raw_payload)
                        VALUES (%s, %s, %s, %s)
                        RETURNING id
                        """,
                        (run_id, event.source, _db_timestamp(event), Json(event.payload_dict())),
                    )
                    webhook_event_id = cursor.fetchone()[0]
                    if self._settings.dedup_enabled:
                        cursor.execute(
                            """
                            UPDATE public.webhook_event_dedup
                            SET webhook_event_id = %s
                            WHERE dedup_key = %s
                            """,
                            (webhook_event_id, event.dedup_key),
                        )
                conn.commit()
                return InsertResult(inserted=True, duplicate=False, webhook_event_id=webhook_event_id)
            except Exception:
                conn.rollback()
                raise

    @contextmanager
    def connection(self) -> Iterator[object]:
        self.open()
        assert self._pool is not None
        conn = self._pool.getconn()
        try:
            yield conn
        finally:
            self._pool.putconn(conn)


def _db_timestamp(event: WebhookEvent):
    return event.received_at.astimezone(UTC).replace(tzinfo=None)
