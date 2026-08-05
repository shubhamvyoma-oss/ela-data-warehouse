from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from psycopg2 import pool
from psycopg2.extras import register_uuid

from shared.config import DatabaseSettings

register_uuid()


class Database:
    """Small lazy PostgreSQL pool with explicit transaction boundaries."""

    def __init__(self, settings: DatabaseSettings, application_name: str) -> None:
        self._settings = settings
        self._application_name = application_name
        self._pool: pool.ThreadedConnectionPool | None = None

    def open(self) -> None:
        if self._pool is None:
            self._pool = pool.ThreadedConnectionPool(
                self._settings.pool_min_connections,
                self._settings.pool_max_connections,
                **self._settings.connection_kwargs(self._application_name),
            )

    def close(self) -> None:
        if self._pool is not None:
            self._pool.closeall()
            self._pool = None

    @contextmanager
    def connection(self) -> Iterator[Any]:
        self.open()
        assert self._pool is not None
        connection = self._pool.getconn()
        try:
            yield connection
        finally:
            self._pool.putconn(connection)

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        with self.connection() as connection:
            try:
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def health_check(self) -> bool:
        try:
            with self.transaction() as connection, connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                return cursor.fetchone()[0] == 1
        except Exception:
            return False
