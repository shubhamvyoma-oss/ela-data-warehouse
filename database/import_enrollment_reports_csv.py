"""One-off: imports the historical ela_datasets enrollments_reports CSV
export into bronze.enrollment_reports.

bronze.enrollment_reports already has the exact matching 22-column schema
for this CSV (see database/migrations/006_legacy_pipeline_bronze_tables.sql)
and a UNIQUE(enrollment_id) constraint, so this is a straightforward
idempotent upsert -- safe to re-run against a newer export of the same CSV.

Source: /home/projectdev/ela_datasets/enrollments_reports/output/edmingle_enrollment_report.csv
(the ela_datasets project's own standalone pipeline output -- read-only,
never modified by this script).

Required environment variables:
  WAREHOUSE_DB_HOST / _PORT / _NAME / _USER / _PASSWORD
"""
from __future__ import annotations

import csv
import os
import socket
import sys
import uuid
from datetime import UTC, datetime

import psycopg2
import psycopg2.extras
from psycopg2.extras import execute_values

psycopg2.extras.register_uuid()

BATCH_SIZE = 1000
PIPELINE_NAME = "enrollment_reports_csv_import"
HOST_NAME = socket.gethostname()

_COLUMNS = [
    "enrollment_id", "enrollment_day", "user_id", "name", "email", "contact_number",
    "contact_number_country_id", "state", "registration_number", "learner_type",
    "enrollment_mode", "enrollment_status", "bundle_id", "bundle_name", "batch_ids",
    "batches", "product_type", "product_type_label", "platform_type",
    "enrollment_expiration_date", "shipping_details_json", "preferred_categories",
]

_UPSERT_SQL = f"""
    INSERT INTO bronze.enrollment_reports (
        pipeline_run_id, {", ".join(_COLUMNS)}, received_at
    ) VALUES %s
    ON CONFLICT (enrollment_id) DO UPDATE SET
        {", ".join(f"{col} = EXCLUDED.{col}" for col in _COLUMNS if col != "enrollment_id")},
        received_at = EXCLUDED.received_at
"""


def _dsn() -> dict:
    def required(name: str) -> str:
        value = os.environ.get(name, "")
        if not value:
            raise SystemExit(f"{name} is required")
        return value

    return dict(
        host=required("WAREHOUSE_DB_HOST"),
        port=int(os.environ.get("WAREHOUSE_DB_PORT", "5432")),
        dbname=required("WAREHOUSE_DB_NAME"),
        user=required("WAREHOUSE_DB_USER"),
        password=required("WAREHOUSE_DB_PASSWORD"),
    )


def main(csv_path: str) -> None:
    conn = psycopg2.connect(**_dsn())
    try:
        run_id = uuid.uuid4()
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO audit.pipeline_runs (id, pipeline_name, run_type, status, host_name)
                VALUES (%s, %s, 'backfill', 'RUNNING', %s)
                """,
                (run_id, PIPELINE_NAME, HOST_NAME),
            )
        conn.commit()

        received_at = datetime.now(UTC)
        rows_read = 0
        rows_written = 0
        batch = []

        with open(csv_path, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            missing = set(_COLUMNS) - set(reader.fieldnames or [])
            if missing:
                raise SystemExit(f"CSV is missing expected columns: {sorted(missing)}")

            with conn.cursor() as cursor:
                for record in reader:
                    if not record.get("enrollment_id", "").strip():
                        continue
                    rows_read += 1
                    values = [run_id] + [
                        (record.get(col) or "").strip() or None for col in _COLUMNS
                    ] + [received_at]
                    batch.append(tuple(values))
                    if len(batch) >= BATCH_SIZE:
                        execute_values(cursor, _UPSERT_SQL, batch, page_size=BATCH_SIZE)
                        rows_written += len(batch)
                        conn.commit()
                        batch = []
                if batch:
                    execute_values(cursor, _UPSERT_SQL, batch, page_size=BATCH_SIZE)
                    rows_written += len(batch)
                    conn.commit()

        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE audit.pipeline_runs
                SET status = 'SUCCESS', finished_at = now(), rows_read = %s, rows_written = %s
                WHERE id = %s
                """,
                (rows_read, rows_written, run_id),
            )
        conn.commit()
        print(f"{csv_path} -> bronze.enrollment_reports: read {rows_read}, upserted {rows_written}")
    finally:
        conn.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python import_enrollment_reports_csv.py <path-to-csv>")
    main(sys.argv[1])
