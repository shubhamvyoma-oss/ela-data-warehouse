from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC

from psycopg2 import pool
from psycopg2.extras import Json

from app.config.settings import Settings
from app.models.event import WebhookEvent

logger = logging.getLogger("webhook.database")


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

                    cursor.execute(
                        """
                        INSERT INTO public.webhook_events (source, received_at, raw_payload)
                        VALUES (%s, %s, %s)
                        RETURNING id
                        """,
                        (event.source, _db_timestamp(event), Json(event.payload_dict())),
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
