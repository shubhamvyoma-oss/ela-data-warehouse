"""Silver transform: bronze.enrollment_reports -> silver.enrollment_reports.

Distinct from any future silver.course_enrollments -- this is a separate
Bronze source (the /reports/enrollment endpoint) from
bronze.course_enrollments (the /admin/classes/attendance endpoint). Whether
these should ever be reconciled into one Silver entity is deferred pending a
business decision (see ROADMAP.md).
"""
from __future__ import annotations

from psycopg2.extras import execute_values

from processing.silver._normalize import (
    DMY_FIRST_DATE_FORMATS,
    clean_email,
    clean_phone,
    clean_text,
    parse_date,
    upper_or_none,
)
from shared.database import Database

_SELECT_SQL = """
    SELECT enrollment_id, enrollment_day, user_id, name, email, contact_number,
           state, registration_number, learner_type, enrollment_mode,
           enrollment_status, bundle_id, bundle_name, batch_ids,
           product_type, product_type_label, platform_type,
           enrollment_expiration_date, preferred_categories, received_at
    FROM bronze.enrollment_reports
    WHERE enrollment_id IS NOT NULL
"""

_UPSERT_SQL = """
    INSERT INTO silver.enrollment_reports (
        enrollment_id, enrollment_day, user_id, name, email, contact_number,
        state, registration_number, learner_type, enrollment_mode,
        enrollment_status, bundle_id, bundle_name, batch_ids,
        product_type, product_type_label, platform_type,
        enrollment_expiration_date, preferred_categories, source_updated_at
    ) VALUES %s
    ON CONFLICT (enrollment_id) DO UPDATE SET
        enrollment_day = EXCLUDED.enrollment_day,
        user_id = EXCLUDED.user_id,
        name = EXCLUDED.name,
        email = EXCLUDED.email,
        contact_number = EXCLUDED.contact_number,
        state = EXCLUDED.state,
        registration_number = EXCLUDED.registration_number,
        learner_type = EXCLUDED.learner_type,
        enrollment_mode = EXCLUDED.enrollment_mode,
        enrollment_status = EXCLUDED.enrollment_status,
        bundle_id = EXCLUDED.bundle_id,
        bundle_name = EXCLUDED.bundle_name,
        batch_ids = EXCLUDED.batch_ids,
        product_type = EXCLUDED.product_type,
        product_type_label = EXCLUDED.product_type_label,
        platform_type = EXCLUDED.platform_type,
        enrollment_expiration_date = EXCLUDED.enrollment_expiration_date,
        preferred_categories = EXCLUDED.preferred_categories,
        source_updated_at = EXCLUDED.source_updated_at,
        silver_updated_at = now()
    RETURNING id
"""


def transform_enrollment_reports(database: Database) -> tuple[int, int]:
    with database.connection() as conn:
        cursor = conn.cursor()
        cursor.execute(_SELECT_SQL)
        rows = cursor.fetchall()

    rows_read = len(rows)
    values = []
    for row in rows:
        (
            enrollment_id, enrollment_day, user_id, name, email, contact_number,
            state, registration_number, learner_type, enrollment_mode,
            enrollment_status, bundle_id, bundle_name, batch_ids,
            product_type, product_type_label, platform_type,
            enrollment_expiration_date, preferred_categories, received_at,
        ) = row

        values.append((
            str(enrollment_id).strip(),
            parse_date(enrollment_day, DMY_FIRST_DATE_FORMATS),
            clean_text(user_id),
            clean_text(name),
            clean_email(email),
            clean_phone(contact_number),
            clean_text(state),
            clean_text(registration_number),
            clean_text(learner_type),
            clean_text(enrollment_mode),
            upper_or_none(enrollment_status),
            clean_text(bundle_id),
            clean_text(bundle_name),
            clean_text(batch_ids),
            clean_text(product_type),
            clean_text(product_type_label),
            clean_text(platform_type),
            parse_date(enrollment_expiration_date, DMY_FIRST_DATE_FORMATS),
            clean_text(preferred_categories),
            received_at,
        ))

    if not values:
        return rows_read, 0

    with database.transaction() as conn:
        cursor = conn.cursor()
        returned = execute_values(cursor, _UPSERT_SQL, values, page_size=500, fetch=True)
        rows_written = len(returned)

    return rows_read, rows_written
