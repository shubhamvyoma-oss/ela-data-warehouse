from __future__ import annotations

import socket
import uuid
from datetime import UTC, datetime
from typing import Any

from psycopg2.extras import Json, execute_values

from api_scripts.common.models import RawRecord
from shared.database import Database


class RunRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def start(self, pipeline_name: str, run_type: str, checkpoint_before: dict[str, Any]) -> uuid.UUID:
        run_id = uuid.uuid4()
        with self.database.transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO audit.pipeline_runs (
                    id, pipeline_name, run_type, status, checkpoint_before, host_name
                ) VALUES (%s, %s, %s, 'RUNNING', %s, %s)
                """,
                (run_id, pipeline_name, run_type, Json(checkpoint_before), socket.gethostname()),
            )
            cursor.execute(
                """
                INSERT INTO audit.events (run_id, component, event_type, status, details)
                VALUES (%s, %s, 'collector_started', 'INFO', '{}'::jsonb)
                """,
                (run_id, pipeline_name),
            )
        return run_id

    def finish(
        self,
        run_id: uuid.UUID,
        pipeline_name: str,
        *,
        status: str,
        rows_read: int,
        rows_written: int,
        rows_rejected: int,
        checkpoint_after: dict[str, Any],
        request_count: int,
        error_category: str | None = None,
    ) -> None:
        database_status = "SUCCESS" if status == "succeeded" else "FAILED"
        event_status = database_status
        event_type = "collector_finished" if status == "succeeded" else "collector_failed"
        with self.database.transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE audit.pipeline_runs
                SET status = %s,
                    finished_at = now(),
                    rows_read = %s,
                    rows_written = %s,
                    rows_rejected = %s,
                    checkpoint_after = %s,
                    metadata = metadata || jsonb_build_object('request_count', %s),
                    error_category = %s,
                    error_message = CASE WHEN %s IS NULL THEN NULL
                                         ELSE 'collector failed; inspect protected application logs' END
                WHERE id = %s
                """,
                (
                    database_status,
                    rows_read,
                    rows_written,
                    rows_rejected,
                    Json(checkpoint_after),
                    request_count,
                    error_category,
                    error_category,
                    run_id,
                ),
            )
            cursor.execute(
                """
                INSERT INTO audit.events (
                    run_id, component, event_type, status, row_count, details
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    run_id,
                    pipeline_name,
                    event_type,
                    event_status,
                    rows_written,
                    Json({
                        "rows_read": rows_read,
                        "rows_rejected": rows_rejected,
                        "request_count": request_count,
                    }),
                ),
            )


class CredentialMetadataRepository:
    """Persist API credential lifecycle metadata; credential values are never accepted."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def upsert_edmingle(self, *, expires_at: datetime | None, status: str) -> None:
        with self.database.transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO system.api_credentials (
                    credential_name, provider, expires_at, status, updated_at
                ) VALUES ('edmingle_api', 'edmingle', %s, %s, now())
                ON CONFLICT (credential_name) DO UPDATE
                SET expires_at = EXCLUDED.expires_at,
                    status = EXCLUDED.status,
                    updated_at = now()
                """,
                (expires_at, status.upper()),
            )


class CheckpointRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def get(self, collector_name: str, partition_key: str = "default") -> dict[str, Any]:
        with self.database.transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT checkpoint
                FROM system.collection_checkpoints
                WHERE collector_name = %s AND partition_key = %s
                """,
                (collector_name, partition_key),
            )
            row = cursor.fetchone()
            return dict(row[0]) if row else {}


class BronzeRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def write_with_checkpoint(
        self,
        *,
        collector_name: str,
        run_id: uuid.UUID,
        records: list[RawRecord],
        checkpoint: dict[str, Any],
        partition_key: str = "default",
    ) -> int:
        inserted = 0
        with self.database.transaction() as connection, connection.cursor() as cursor:
            if records:
                values = [
                    (
                        record.resource,
                        record.record_key,
                        record.source_updated_at,
                        record.received_at,
                        run_id,
                        record.checksum,
                        Json(record.request_context),
                        Json(record.payload),
                    )
                    for record in records
                ]
                returned = execute_values(
                    cursor,
                    """
                    INSERT INTO bronze.edmingle_api_records (
                        resource, record_key, source_updated_at, received_at,
                        pipeline_run_id, payload_sha256, request_context, raw_payload
                    ) VALUES %s
                    ON CONFLICT DO NOTHING
                    RETURNING id
                    """,
                    values,
                    page_size=500,
                    fetch=True,
                )
                inserted = len(returned)
            cursor.execute(
                """
                INSERT INTO system.collection_checkpoints (
                    collector_name, partition_key, checkpoint, updated_at, last_committed_run_id
                ) VALUES (%s, %s, %s, now(), %s)
                ON CONFLICT (collector_name, partition_key) DO UPDATE
                SET checkpoint = EXCLUDED.checkpoint,
                    updated_at = now(),
                    last_committed_run_id = EXCLUDED.last_committed_run_id
                """,
                (collector_name, partition_key, Json(checkpoint), run_id),
            )
            cursor.execute(
                """
                INSERT INTO audit.events (
                    run_id, component, event_type, status, row_count, details
                ) VALUES (%s, %s, 'checkpoint_committed', 'SUCCESS', %s, %s)
                """,
                (
                    run_id,
                    collector_name,
                    inserted,
                    Json({"partition_key": partition_key, "received_records": len(records)}),
                ),
            )
        return inserted


class TransformedTableRepository:
    """Writes already-transformed rows from ported legacy pipelines into their
    own dedicated Bronze tables (e.g. bronze.course_catalog, bronze.students) --
    distinct from BronzeRepository, which only knows bronze.edmingle_api_records'
    raw-payload shape. Table and column names are always static strings chosen
    by the calling collector, never derived from API response data, so building
    SQL from them here is safe.

    This is a deliberate, explicit exception to "Bronze holds only raw
    payloads" for the ported-legacy-pipeline tables -- see
    documentation/decisions and the migration 006 comment for context.
    """

    def __init__(self, database: Database) -> None:
        self.database = database

    def write_with_checkpoint(
        self,
        *,
        table: str,
        columns: list[str],
        rows: list[tuple[Any, ...]],
        unique_columns: list[str],
        collector_name: str,
        run_id: uuid.UUID,
        checkpoint: dict[str, Any],
        partition_key: str = "default",
    ) -> int:
        inserted = 0
        with self.database.transaction() as connection, connection.cursor() as cursor:
            if rows:
                received_at = datetime.now(UTC)
                all_columns = ["pipeline_run_id", "received_at", *columns]
                values = [(run_id, received_at, *row) for row in rows]
                update_columns = [c for c in columns if c not in unique_columns]
                if update_columns:
                    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_columns)
                    on_conflict_sql = f"ON CONFLICT ({', '.join(unique_columns)}) DO UPDATE SET {set_clause}"
                else:
                    on_conflict_sql = f"ON CONFLICT ({', '.join(unique_columns)}) DO NOTHING"
                returned = execute_values(
                    cursor,
                    f"""
                    INSERT INTO {table} ({', '.join(all_columns)})
                    VALUES %s
                    {on_conflict_sql}
                    RETURNING id
                    """,
                    values,
                    page_size=500,
                    fetch=True,
                )
                inserted = len(returned)
            cursor.execute(
                """
                INSERT INTO system.collection_checkpoints (
                    collector_name, partition_key, checkpoint, updated_at, last_committed_run_id
                ) VALUES (%s, %s, %s, now(), %s)
                ON CONFLICT (collector_name, partition_key) DO UPDATE
                SET checkpoint = EXCLUDED.checkpoint,
                    updated_at = now(),
                    last_committed_run_id = EXCLUDED.last_committed_run_id
                """,
                (collector_name, partition_key, Json(checkpoint), run_id),
            )
            cursor.execute(
                """
                INSERT INTO audit.events (
                    run_id, component, event_type, status, row_count, details
                ) VALUES (%s, %s, 'checkpoint_committed', 'SUCCESS', %s, %s)
                """,
                (
                    run_id,
                    collector_name,
                    inserted,
                    Json({"partition_key": partition_key, "received_rows": len(rows), "table": table}),
                ),
            )
        return inserted


def utc_iso() -> str:
    return datetime.now(UTC).isoformat()
