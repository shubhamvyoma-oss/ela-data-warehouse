"""Silver transform: bronze.course_enrollments -> silver.course_enrollments.

Single Bronze source, no reconciliation needed. Distinct from
silver.enrollment_reports (different source script, different endpoint,
different grain -- per-(student, class) attendance summary here vs. a
historical per-enrollment-event log there) -- kept as separate Silver
entities per project-owner decision, see ROADMAP.md.

start_date/end_date/classusers_start_date/classusers_end_date/archived_at
are passed through as cleaned text, not parsed into dates: the source API's
exact date format for these fields has never been confirmed against a live
sample (the Bronze job itself only ever passed them through as plain
text), so guessing a parse format here risks silently producing wrong dates.
"""
from __future__ import annotations

from psycopg2.extras import execute_values

from processing.silver._normalize import clean_email, clean_text, parse_int
from shared.database import Database

_SELECT_SQL = """
    SELECT user_id, class_id, name, email, class_name, tutor_name,
           total_classes, present_count, absent_count, late_count,
           excused_count, start_date, end_date, master_batch_id,
           master_batch_name, classusers_start_date, classusers_end_date,
           batch_status, cu_status, cu_state, institution_bundle_id,
           archived_at, bundle_id, received_at
    FROM bronze.course_enrollments
    WHERE user_id IS NOT NULL AND class_id IS NOT NULL
"""

_UPSERT_SQL = """
    INSERT INTO silver.course_enrollments (
        user_id, class_id, name, email, class_name, tutor_name,
        total_classes, present_count, absent_count, late_count,
        excused_count, start_date, end_date, master_batch_id,
        master_batch_name, classusers_start_date, classusers_end_date,
        batch_status, cu_status, cu_state, institution_bundle_id,
        archived_at, bundle_id, source_updated_at
    ) VALUES %s
    ON CONFLICT (user_id, class_id) DO UPDATE SET
        name = EXCLUDED.name,
        email = EXCLUDED.email,
        class_name = EXCLUDED.class_name,
        tutor_name = EXCLUDED.tutor_name,
        total_classes = EXCLUDED.total_classes,
        present_count = EXCLUDED.present_count,
        absent_count = EXCLUDED.absent_count,
        late_count = EXCLUDED.late_count,
        excused_count = EXCLUDED.excused_count,
        start_date = EXCLUDED.start_date,
        end_date = EXCLUDED.end_date,
        master_batch_id = EXCLUDED.master_batch_id,
        master_batch_name = EXCLUDED.master_batch_name,
        classusers_start_date = EXCLUDED.classusers_start_date,
        classusers_end_date = EXCLUDED.classusers_end_date,
        batch_status = EXCLUDED.batch_status,
        cu_status = EXCLUDED.cu_status,
        cu_state = EXCLUDED.cu_state,
        institution_bundle_id = EXCLUDED.institution_bundle_id,
        archived_at = EXCLUDED.archived_at,
        bundle_id = EXCLUDED.bundle_id,
        source_updated_at = EXCLUDED.source_updated_at,
        silver_updated_at = now()
    RETURNING id
"""


def transform_course_enrollments(database: Database) -> tuple[int, int]:
    with database.connection() as conn:
        cursor = conn.cursor()
        cursor.execute(_SELECT_SQL)
        rows = cursor.fetchall()

    rows_read = len(rows)
    values = []
    for row in rows:
        (
            user_id, class_id, name, email, class_name, tutor_name,
            total_classes, present_count, absent_count, late_count,
            excused_count, start_date, end_date, master_batch_id,
            master_batch_name, classusers_start_date, classusers_end_date,
            batch_status, cu_status, cu_state, institution_bundle_id,
            archived_at, bundle_id, received_at,
        ) = row

        values.append((
            str(user_id).strip(),
            str(class_id).strip(),
            clean_text(name),
            clean_email(email),
            clean_text(class_name),
            clean_text(tutor_name),
            parse_int(total_classes),
            parse_int(present_count),
            parse_int(absent_count),
            parse_int(late_count),
            parse_int(excused_count),
            clean_text(start_date),
            clean_text(end_date),
            clean_text(master_batch_id),
            clean_text(master_batch_name),
            clean_text(classusers_start_date),
            clean_text(classusers_end_date),
            clean_text(batch_status),
            clean_text(cu_status),
            clean_text(cu_state),
            clean_text(institution_bundle_id),
            clean_text(archived_at),
            clean_text(bundle_id),
            received_at,
        ))

    if not values:
        return rows_read, 0

    with database.transaction() as conn:
        cursor = conn.cursor()
        returned = execute_values(cursor, _UPSERT_SQL, values, page_size=500, fetch=True)
        rows_written = len(returned)

    return rows_read, rows_written
