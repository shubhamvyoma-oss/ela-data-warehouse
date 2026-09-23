"""Silver transform: bronze.report55_batch_attendance_summary -> silver.report55_batch_attendance_summary.

Single Bronze source, no reconciliation needed. Distinct from
silver.class_session_attendance (different endpoint: report_type=55's
student-mark rollups vs. /organization/attendances' pre-aggregated
session totals) -- kept as separate Silver entities per project-owner
decision, see ROADMAP.md.
"""
from __future__ import annotations

from psycopg2.extras import execute_values

from processing.silver._normalize import clean_text, parse_int
from shared.database import Database

_SELECT_SQL = """
    SELECT batch_id, summary_window_start, summary_window_end, batch_name,
           bundle_id, bundle_name, course_id, course_name, teacher_id,
           teacher_name, total_students_enrolled, first_class_date,
           last_class_date, first_class_attendance, last_class_attendance,
           total_present_marks, total_absent_marks, attendance_percentage,
           average_class_attendance, highest_class_attendance,
           lowest_class_attendance, average_rating, retention_percentage,
           attendance_drop, received_at
    FROM bronze.report55_batch_attendance_summary
    WHERE batch_id IS NOT NULL
"""

_UPSERT_SQL = """
    INSERT INTO silver.report55_batch_attendance_summary (
        batch_id, summary_window_start, summary_window_end, batch_name,
        bundle_id, bundle_name, course_id, course_name, teacher_id,
        teacher_name, total_students_enrolled, first_class_date,
        last_class_date, first_class_attendance, last_class_attendance,
        total_present_marks, total_absent_marks, attendance_percentage,
        average_class_attendance, highest_class_attendance,
        lowest_class_attendance, average_rating, retention_percentage,
        attendance_drop, source_updated_at
    ) VALUES %s
    ON CONFLICT (batch_id, summary_window_start, summary_window_end) DO UPDATE SET
        batch_name = EXCLUDED.batch_name,
        bundle_id = EXCLUDED.bundle_id,
        bundle_name = EXCLUDED.bundle_name,
        course_id = EXCLUDED.course_id,
        course_name = EXCLUDED.course_name,
        teacher_id = EXCLUDED.teacher_id,
        teacher_name = EXCLUDED.teacher_name,
        total_students_enrolled = EXCLUDED.total_students_enrolled,
        first_class_date = EXCLUDED.first_class_date,
        last_class_date = EXCLUDED.last_class_date,
        first_class_attendance = EXCLUDED.first_class_attendance,
        last_class_attendance = EXCLUDED.last_class_attendance,
        total_present_marks = EXCLUDED.total_present_marks,
        total_absent_marks = EXCLUDED.total_absent_marks,
        attendance_percentage = EXCLUDED.attendance_percentage,
        average_class_attendance = EXCLUDED.average_class_attendance,
        highest_class_attendance = EXCLUDED.highest_class_attendance,
        lowest_class_attendance = EXCLUDED.lowest_class_attendance,
        average_rating = EXCLUDED.average_rating,
        retention_percentage = EXCLUDED.retention_percentage,
        attendance_drop = EXCLUDED.attendance_drop,
        source_updated_at = EXCLUDED.source_updated_at,
        silver_updated_at = now()
    RETURNING id
"""


def transform_report55_batch_attendance_summary(database: Database) -> tuple[int, int]:
    with database.connection() as conn:
        cursor = conn.cursor()
        cursor.execute(_SELECT_SQL)
        rows = cursor.fetchall()

    rows_read = len(rows)
    values = []
    for row in rows:
        (
            batch_id, summary_window_start, summary_window_end, batch_name,
            bundle_id, bundle_name, course_id, course_name, teacher_id,
            teacher_name, total_students_enrolled, first_class_date,
            last_class_date, first_class_attendance, last_class_attendance,
            total_present_marks, total_absent_marks, attendance_percentage,
            average_class_attendance, highest_class_attendance,
            lowest_class_attendance, average_rating, retention_percentage,
            attendance_drop, received_at,
        ) = row

        values.append((
            str(batch_id).strip(),
            summary_window_start,
            summary_window_end,
            clean_text(batch_name),
            clean_text(bundle_id),
            clean_text(bundle_name),
            clean_text(course_id),
            clean_text(course_name),
            clean_text(teacher_id),
            clean_text(teacher_name),
            parse_int(total_students_enrolled),
            first_class_date,
            last_class_date,
            parse_int(first_class_attendance),
            parse_int(last_class_attendance),
            parse_int(total_present_marks),
            parse_int(total_absent_marks),
            attendance_percentage,
            average_class_attendance,
            parse_int(highest_class_attendance),
            parse_int(lowest_class_attendance),
            average_rating,
            retention_percentage,
            parse_int(attendance_drop),
            received_at,
        ))

    if not values:
        return rows_read, 0

    with database.transaction() as conn:
        cursor = conn.cursor()
        returned = execute_values(cursor, _UPSERT_SQL, values, page_size=500, fetch=True)
        rows_written = len(returned)

    return rows_read, rows_written
