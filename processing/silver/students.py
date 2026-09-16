"""Silver transform: bronze.students -> silver.students.

Typed/normalized pass over a single Bronze source -- no reconciliation with
another source is needed here, unlike the catalogue/attendance/enrollment
domains (see ROADMAP.md for why those are deferred).
"""
from __future__ import annotations

from psycopg2.extras import execute_values

from processing.silver._normalize import (
    clean_email,
    clean_phone,
    clean_text,
    lower_or_none,
    parse_date,
    parse_int,
    upper_or_none,
)
from shared.database import Database

_SELECT_SQL = """
    SELECT user_id, name, email, contact_number, contact_number_2,
           parent_name, parent_email, parent_contact_number,
           registration_number, role, status, is_archived,
           registration_date, custom_age, custom_last_name,
           custom_user_name, user_username, received_at
    FROM bronze.students
    WHERE user_id IS NOT NULL
"""

_UPSERT_SQL = """
    INSERT INTO silver.students (
        user_id, name, email, primary_contact_number, secondary_contact_number,
        parent_name, parent_email, parent_contact_number, registration_number,
        role, status, is_archived, registration_date, age, last_name, username,
        source_updated_at
    ) VALUES %s
    ON CONFLICT (user_id) DO UPDATE SET
        name = EXCLUDED.name,
        email = EXCLUDED.email,
        primary_contact_number = EXCLUDED.primary_contact_number,
        secondary_contact_number = EXCLUDED.secondary_contact_number,
        parent_name = EXCLUDED.parent_name,
        parent_email = EXCLUDED.parent_email,
        parent_contact_number = EXCLUDED.parent_contact_number,
        registration_number = EXCLUDED.registration_number,
        role = EXCLUDED.role,
        status = EXCLUDED.status,
        is_archived = EXCLUDED.is_archived,
        registration_date = EXCLUDED.registration_date,
        age = EXCLUDED.age,
        last_name = EXCLUDED.last_name,
        username = EXCLUDED.username,
        source_updated_at = EXCLUDED.source_updated_at,
        silver_updated_at = now()
    RETURNING id
"""


def transform_students(database: Database) -> tuple[int, int]:
    with database.connection() as conn:
        cursor = conn.cursor()
        cursor.execute(_SELECT_SQL)
        rows = cursor.fetchall()

    rows_read = len(rows)
    values = []
    for row in rows:
        (
            user_id, name, email, contact_number, contact_number_2,
            parent_name, parent_email, parent_contact_number,
            registration_number, role, status, is_archived,
            registration_date, custom_age, custom_last_name,
            custom_user_name, user_username, received_at,
        ) = row

        values.append((
            str(user_id).strip(),
            clean_text(name),
            clean_email(email),
            clean_phone(contact_number),
            clean_phone(contact_number_2),
            clean_text(parent_name),
            clean_email(parent_email),
            clean_phone(parent_contact_number),
            clean_text(registration_number),
            lower_or_none(role),
            upper_or_none(status),
            is_archived,
            parse_date(registration_date),
            parse_int(custom_age),
            clean_text(custom_last_name),
            clean_text(custom_user_name) or clean_text(user_username),
            received_at,
        ))

    if not values:
        return rows_read, 0

    with database.transaction() as conn:
        cursor = conn.cursor()
        returned = execute_values(cursor, _UPSERT_SQL, values, page_size=500, fetch=True)
        rows_written = len(returned)

    return rows_read, rows_written
