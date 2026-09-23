"""Silver transform: bronze.report55_session_attendance -> silver.report55_session_attendance.

Single Bronze source, no reconciliation needed. Distinct from
silver.class_session_attendance (different endpoint: report_type=55's
student-mark rollups vs. /organization/attendances' pre-aggregated
session totals; session_number is scoped per batch_id here vs. per
master_batch_id there) -- kept as separate Silver entities per
project-owner decision, see ROADMAP.md.
"""
from __future__ import annotations

from psycopg2.extras import execute_values

from processing.silver._normalize import clean_text, parse_int
from shared.database import Database

_SELECT_SQL = """
    SELECT batch_id, session_id, batch_name, course_id, course_name,
           session_number, class_date, is_session_conducted, present_count,
           absent_count, late_count, total_marked,
           session_attendance_percentage, received_at
    FROM bronze.report55_session_attendance
    WHERE batch_id IS NOT NULL AND session_id IS NOT NULL
"""

_UPSERT_SQL = """
    INSERT INTO silver.report55_session_attendance (
        batch_id, session_id, batch_name, course_id, course_name,
        session_number, class_date, is_session_conducted, present_count,
        absent_count, late_count, total_marked,
        session_attendance_percentage, source_updated_at
    ) VALUES %s
    ON CONFLICT (batch_id, session_id) DO UPDATE SET
        batch_name = EXCLUDED.batch_name,
        course_id = EXCLUDED.course_id,
        course_name = EXCLUDED.course_name,
        session_number = EXCLUDED.session_number,
        class_date = EXCLUDED.class_date,
        is_session_conducted = EXCLUDED.is_session_conducted,
        present_count = EXCLUDED.present_count,
        absent_count = EXCLUDED.absent_count,
        late_count = EXCLUDED.late_count,
        total_marked = EXCLUDED.total_marked,
        session_attendance_percentage = EXCLUDED.session_attendance_percentage,
        source_updated_at = EXCLUDED.source_updated_at,
        silver_updated_at = now()
    RETURNING id
"""


def transform_report55_session_attendance(database: Database) -> tuple[int, int]:
    with database.connection() as conn:
        cursor = conn.cursor()
        cursor.execute(_SELECT_SQL)
        rows = cursor.fetchall()

    rows_read = len(rows)
    values = []
    for row in rows:
        (
            batch_id, session_id, batch_name, course_id, course_name,
            session_number, class_date, is_session_conducted, present_count,
            absent_count, late_count, total_marked,
            session_attendance_percentage, received_at,
        ) = row

        values.append((
            str(batch_id).strip(),
            str(session_id).strip(),
            clean_text(batch_name),
            clean_text(course_id),
            clean_text(course_name),
            parse_int(session_number),
            class_date,
            is_session_conducted,
            parse_int(present_count),
            parse_int(absent_count),
            parse_int(late_count),
            parse_int(total_marked),
            session_attendance_percentage,
            received_at,
        ))

    if not values:
        return rows_read, 0

    with database.transaction() as conn:
        cursor = conn.cursor()
        returned = execute_values(cursor, _UPSERT_SQL, values, page_size=500, fetch=True)
        rows_written = len(returned)

    return rows_read, rows_written
