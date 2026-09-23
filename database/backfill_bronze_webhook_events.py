"""One-off backfill: copies historical webhook events from two source tables
into bronze.webhook_events, with full audit lineage (one audit.pipeline_runs
row per source) and idempotent re-run safety (ON CONFLICT DO NOTHING on
(legacy_source_database, legacy_source_id)).

Already run successfully on 2026-09-23 (46,312 rows: 36,777 from webhook_db,
9,535 from this database's own public.webhook_events -- see migration
011_bronze_webhook_events.sql's own header for the full context). Kept here
for the historical record and in case it's ever needed again (e.g. against a
restored/rebuilt database) -- safe to re-run, already-backfilled rows are
skipped via the unique constraint.

Sources (read-only, never modified):
  1. webhook_db.public.webhook_events        (separate Postgres database --
     the standalone legacy edmingle-webhook project's own storage)
  2. this database's own public.webhook_events (the webhook service's
     storage before its live write path was redirected to insert into
     bronze.webhook_events directly)

Destination: bronze.webhook_events (migration 011_bronze_webhook_events.sql).

Required environment variables:
  WAREHOUSE_DB_HOST / _PORT / _NAME / _USER / _PASSWORD  -- destination
  LEGACY_WEBHOOK_DB_HOST / _PORT / _NAME / _USER / _PASSWORD  -- source 1
"""
from __future__ import annotations

import os
import socket
import uuid
from datetime import UTC, datetime

import psycopg2
import psycopg2.extras
from psycopg2.extras import Json, execute_values

psycopg2.extras.register_uuid()

BATCH_SIZE = 1000
PIPELINE_NAME = "webhook_ingestion"
HOST_NAME = socket.gethostname()


def _required_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def _dsn(prefix: str) -> dict:
    return dict(
        host=_required_env(f"{prefix}_HOST"),
        port=int(os.environ.get(f"{prefix}_PORT", "5432")),
        dbname=_required_env(f"{prefix}_NAME"),
        user=_required_env(f"{prefix}_USER"),
        password=_required_env(f"{prefix}_PASSWORD"),
    )


def start_run(warehouse_conn, run_type: str, checkpoint_before: dict) -> uuid.UUID:
    run_id = uuid.uuid4()
    with warehouse_conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO audit.pipeline_runs (
                id, pipeline_name, run_type, status, checkpoint_before, host_name
            ) VALUES (%s, %s, %s, 'RUNNING', %s, %s)
            """,
            (run_id, PIPELINE_NAME, run_type, Json(checkpoint_before), HOST_NAME),
        )
        cursor.execute(
            """
            INSERT INTO audit.events (run_id, component, event_type, status, details)
            VALUES (%s, %s, 'backfill_started', 'INFO', '{}'::jsonb)
            """,
            (run_id, PIPELINE_NAME),
        )
    warehouse_conn.commit()
    return run_id


def finish_run(
    warehouse_conn, run_id: uuid.UUID, rows_read: int, rows_written: int, checkpoint_after: dict
) -> None:
    with warehouse_conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE audit.pipeline_runs
            SET status = 'SUCCESS', finished_at = now(),
                rows_read = %s, rows_written = %s, checkpoint_after = %s
            WHERE id = %s
            """,
            (rows_read, rows_written, Json(checkpoint_after), run_id),
        )
        cursor.execute(
            """
            INSERT INTO audit.events (run_id, component, event_type, status, row_count, details)
            VALUES (%s, %s, 'backfill_finished', 'SUCCESS', %s, %s)
            """,
            (run_id, PIPELINE_NAME, rows_written, Json(checkpoint_after)),
        )
    warehouse_conn.commit()


_UPSERT_SQL = """
    INSERT INTO bronze.webhook_events (
        pipeline_run_id, source, received_at, raw_payload,
        legacy_source_database, legacy_source_id
    ) VALUES %s
    ON CONFLICT (legacy_source_database, legacy_source_id) DO NOTHING
"""


def backfill_source(
    warehouse_conn, source_conn, legacy_source_database: str, run_type: str
) -> tuple[int, int]:
    with source_conn.cursor(name="backfill_cursor") as read_cursor:
        read_cursor.itersize = BATCH_SIZE
        read_cursor.execute(
            "SELECT id, source, received_at, raw_payload FROM public.webhook_events ORDER BY id"
        )

        rows_read = 0
        rows_written = 0
        max_source_id = None
        run_id = start_run(
            warehouse_conn, run_type,
            {"legacy_source_database": legacy_source_database, "started_at": datetime.now(UTC).isoformat()},
        )

        batch = []
        with warehouse_conn.cursor() as write_cursor:
            for source_id, source_field, received_at, raw_payload in read_cursor:
                rows_read += 1
                max_source_id = source_id
                batch.append(
                    (run_id, source_field, received_at, Json(raw_payload), legacy_source_database, source_id)
                )
                if len(batch) >= BATCH_SIZE:
                    execute_values(write_cursor, _UPSERT_SQL, batch, page_size=BATCH_SIZE)
                    rows_written += write_cursor.rowcount
                    warehouse_conn.commit()
                    batch = []
            if batch:
                execute_values(write_cursor, _UPSERT_SQL, batch, page_size=BATCH_SIZE)
                rows_written += write_cursor.rowcount
                warehouse_conn.commit()

        finish_run(
            warehouse_conn, run_id, rows_read, rows_written,
            {
                "legacy_source_database": legacy_source_database,
                "max_source_id": max_source_id,
                "rows_read": rows_read,
            },
        )
        return rows_read, rows_written


def main() -> None:
    warehouse_dsn = _dsn("WAREHOUSE_DB")
    legacy_dsn = _dsn("LEGACY_WEBHOOK_DB")

    warehouse_conn = psycopg2.connect(**warehouse_dsn)
    try:
        # Source 1: webhook_db (a separate Postgres database)
        legacy_conn = psycopg2.connect(**legacy_dsn)
        try:
            read1, written1 = backfill_source(warehouse_conn, legacy_conn, "webhook_db", "backfill")
            print(f"webhook_db -> bronze.webhook_events: read {read1}, newly written {written1}")
        finally:
            legacy_conn.close()

        # Source 2: this same database's own public.webhook_events -- a SEPARATE
        # connection from warehouse_conn is required even though it's the same
        # database: the read side uses a named (server-side) cursor, and
        # committing on that same connection mid-batch (which the write side
        # does) would terminate the cursor's portal and break iteration.
        warehouse_read_conn = psycopg2.connect(**warehouse_dsn)
        try:
            read2, written2 = backfill_source(
                warehouse_conn, warehouse_read_conn, "ela_data_warehouse_public", "backfill"
            )
            print(
                f"this database's own public.webhook_events -> bronze.webhook_events: "
                f"read {read2}, newly written {written2}"
            )
        finally:
            warehouse_read_conn.close()
    finally:
        warehouse_conn.close()


if __name__ == "__main__":
    main()
