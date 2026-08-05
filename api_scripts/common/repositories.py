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
                INSERT INTO system.pipeline_runs (
                    run_id, pipeline_name, run_type, status, checkpoint_before, host_name
                ) VALUES (%s, %s, %s, 'running', %s, %s)
                """,
                (run_id, pipeline_name, run_type, Json(checkpoint_before), socket.gethostname()),
            )
            cursor.execute(
                """
                INSERT INTO system.audit_events (run_id, component, event_type, status, details)
                VALUES (%s, %s, 'collector_started', 'info', '{}'::jsonb)
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
        event_status = "succeeded" if status == "succeeded" else "failed"
        event_type = "collector_finished" if status == "succeeded" else "collector_failed"
        with self.database.transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE system.pipeline_runs
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
                WHERE run_id = %s
                """,
                (
                    status,
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
                INSERT INTO system.audit_events (
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
                INSERT INTO system.credential_metadata (
                    credential_name, provider, expires_at, status, updated_at
                ) VALUES ('edmingle_api', 'edmingle', %s, %s, now())
                ON CONFLICT (credential_name) DO UPDATE
                SET expires_at = EXCLUDED.expires_at,
                    status = EXCLUDED.status,
                    updated_at = now()
                """,
                (expires_at, status),
            )


class CheckpointRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def get(self, collector_name: str, partition_key: str = "default") -> dict[str, Any]:
        with self.database.transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT checkpoint
                FROM system.collector_checkpoints
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
                        record.collected_at,
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
                        resource, record_key, source_updated_at, collected_at,
                        pipeline_run_id, payload_sha256, request_context, raw_payload
                    ) VALUES %s
                    ON CONFLICT DO NOTHING
                    RETURNING bronze_record_id
                    """,
                    values,
                    page_size=500,
                    fetch=True,
                )
                inserted = len(returned)
            cursor.execute(
                """
                INSERT INTO system.collector_checkpoints (
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
                INSERT INTO system.audit_events (
                    run_id, component, event_type, status, row_count, details
                ) VALUES (%s, %s, 'checkpoint_committed', 'succeeded', %s, %s)
                """,
                (
                    run_id,
                    collector_name,
                    inserted,
                    Json({"partition_key": partition_key, "received_records": len(records)}),
                ),
            )
        return inserted


def utc_iso() -> str:
    return datetime.now(UTC).isoformat()
