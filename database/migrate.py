from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import psycopg2

from shared.config import DatabaseSettings, WarehouseSettings
from shared.logging import configure_logging

LOGGER = logging.getLogger("warehouse.migrations")
MIGRATION_DIRECTORY = Path(__file__).with_name("migrations")
LOCK_NAME = "ela_data_warehouse_migrations"


class MigrationError(RuntimeError):
    pass


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def apply_migrations(
    database_settings: DatabaseSettings,
    migration_directory: Path = MIGRATION_DIRECTORY,
) -> list[str]:
    files = sorted(migration_directory.glob("[0-9][0-9][0-9]_*.sql"))
    if not files:
        raise MigrationError(f"no migrations found in {migration_directory}")

    connection = psycopg2.connect(
        **database_settings.connection_kwargs("ela-warehouse-migrations")
    )
    applied_now: list[str] = []
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_lock(hashtext(%s))", (LOCK_NAME,))
            cursor.execute("CREATE SCHEMA IF NOT EXISTS system")
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS system.schema_migrations (
                    version text PRIMARY KEY,
                    checksum_sha256 text NOT NULL,
                    applied_at timestamp with time zone NOT NULL DEFAULT now()
                )
                """
            )
            connection.commit()

        for path in files:
            version = path.stem
            checksum = _checksum(path)
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT checksum_sha256 FROM system.schema_migrations WHERE version = %s",
                    (version,),
                )
                existing = cursor.fetchone()
                if existing:
                    if existing[0] != checksum:
                        raise MigrationError(
                            f"migration {version} changed after it was applied"
                        )
                    LOGGER.info("migration already applied", extra={"version": version})
                    continue
                try:
                    cursor.execute(path.read_text(encoding="utf-8"))
                    cursor.execute(
                        """
                        INSERT INTO system.schema_migrations (version, checksum_sha256)
                        VALUES (%s, %s)
                        """,
                        (version, checksum),
                    )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                applied_now.append(version)
                LOGGER.info("migration applied", extra={"version": version})
        return applied_now
    finally:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(hashtext(%s))", (LOCK_NAME,))
            connection.commit()
        finally:
            connection.close()


def main() -> int:
    warehouse_settings = WarehouseSettings.from_environment()
    configure_logging(warehouse_settings.log_level)
    applied = apply_migrations(DatabaseSettings.from_environment())
    LOGGER.info("migration run complete", extra={"applied_count": len(applied)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
