"""Silver transform: bronze.class_session_attendance -> silver.class_session_attendance.

Single Bronze source, no reconciliation needed. Distinct from
silver.report55_session_attendance (different endpoint: /organization/
attendances' pre-aggregated session totals vs. report_type=55's
student-mark rollups; session_number is scoped per master_batch_id here
vs. per batch_id there) -- kept as separate Silver entities per
project-owner decision, see ROADMAP.md.
"""
from __future__ import annotations

from psycopg2.extras import execute_values

from processing.silver._normalize import clean_text, parse_int
from shared.database import Database

_SELECT_SQL = """
    SELECT session_id, class_id, class_name, master_batch_id,
           master_batch_name, bundle_id, bundle_name, class_date,
           total_enrolled_at_session, present_count, not_marked_count,
           attendance_pct, taken_by_name, individual_batch_attendance,
           session_start_ist, session_end_ist, session_duration_minutes,
           is_session_conducted, session_number, received_at
    FROM bronze.class_session_attendance
    WHERE session_id IS NOT NULL
"""

_UPSERT_SQL = """
    INSERT INTO silver.class_session_attendance (
        session_id, class_id, class_name, master_batch_id, master_batch_name,
        bundle_id, bundle_name, class_date, total_enrolled_at_session,
        present_count, not_marked_count, attendance_pct, taken_by_name,
        individual_batch_attendance, session_start_ist, session_end_ist,
        session_duration_minutes, is_session_conducted, session_number,
        source_updated_at
    ) VALUES %s
    ON CONFLICT (session_id) DO UPDATE SET
        class_id = EXCLUDED.class_id,
        class_name = EXCLUDED.class_name,
        master_batch_id = EXCLUDED.master_batch_id,
        master_batch_name = EXCLUDED.master_batch_name,
        bundle_id = EXCLUDED.bundle_id,
        bundle_name = EXCLUDED.bundle_name,
        class_date = EXCLUDED.class_date,
        total_enrolled_at_session = EXCLUDED.total_enrolled_at_session,
        present_count = EXCLUDED.present_count,
        not_marked_count = EXCLUDED.not_marked_count,
        attendance_pct = EXCLUDED.attendance_pct,
        taken_by_name = EXCLUDED.taken_by_name,
        individual_batch_attendance = EXCLUDED.individual_batch_attendance,
        session_start_ist = EXCLUDED.session_start_ist,
        session_end_ist = EXCLUDED.session_end_ist,
        session_duration_minutes = EXCLUDED.session_duration_minutes,
        is_session_conducted = EXCLUDED.is_session_conducted,
        session_number = EXCLUDED.session_number,
        source_updated_at = EXCLUDED.source_updated_at,
        silver_updated_at = now()
    RETURNING id
"""


def transform_class_session_attendance(database: Database) -> tuple[int, int]:
    with database.connection() as conn:
        cursor = conn.cursor()
        cursor.execute(_SELECT_SQL)
        rows = cursor.fetchall()

    rows_read = len(rows)
    values = []
    for row in rows:
        (
            session_id, class_id, class_name, master_batch_id,
            master_batch_name, bundle_id, bundle_name, class_date,
            total_enrolled_at_session, present_count, not_marked_count,
            attendance_pct, taken_by_name, individual_batch_attendance,
            session_start_ist, session_end_ist, session_duration_minutes,
            is_session_conducted, session_number, received_at,
        ) = row

        values.append((
            str(session_id).strip(),
            clean_text(class_id),
            clean_text(class_name),
            clean_text(master_batch_id),
            clean_text(master_batch_name),
            clean_text(bundle_id),
            clean_text(bundle_name),
            class_date,
            parse_int(total_enrolled_at_session),
            parse_int(present_count),
            parse_int(not_marked_count),
            attendance_pct,
            clean_text(taken_by_name),
            clean_text(individual_batch_attendance),
            session_start_ist,
            session_end_ist,
            session_duration_minutes,
            is_session_conducted,
            parse_int(session_number),
            received_at,
        ))

    if not values:
        return rows_read, 0

    with database.transaction() as conn:
        cursor = conn.cursor()
        returned = execute_values(cursor, _UPSERT_SQL, values, page_size=500, fetch=True)
        rows_written = len(returned)

    return rows_read, rows_written
