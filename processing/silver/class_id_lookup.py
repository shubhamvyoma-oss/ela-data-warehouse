"""Silver transform: bronze.class_id_lookup -> silver.class_id_lookup.

Rows with no resolved class_id are meaningful in Bronze (they prove the
batch was checked and genuinely has zero classes) but aren't useful in
Silver, so they're excluded here rather than carried forward.
"""
from __future__ import annotations

from psycopg2.extras import execute_values

from processing.silver._normalize import clean_text, parse_int
from shared.database import Database

_SELECT_SQL = """
    SELECT batch_id, class_id, bundle_id, bundle_name, batch_name,
           tutor_id, tutor_name, total_classes, completed_classes,
           cancelled_classes, num_users, associated_masterbatches, received_at
    FROM bronze.class_id_lookup
    WHERE batch_id IS NOT NULL AND class_id IS NOT NULL
"""

_UPSERT_SQL = """
    INSERT INTO silver.class_id_lookup (
        batch_id, class_id, bundle_id, bundle_name, batch_name,
        tutor_id, tutor_name, total_classes, completed_classes,
        cancelled_classes, num_users, associated_masterbatches, source_updated_at
    ) VALUES %s
    ON CONFLICT (batch_id, class_id) DO UPDATE SET
        bundle_id = EXCLUDED.bundle_id,
        bundle_name = EXCLUDED.bundle_name,
        batch_name = EXCLUDED.batch_name,
        tutor_id = EXCLUDED.tutor_id,
        tutor_name = EXCLUDED.tutor_name,
        total_classes = EXCLUDED.total_classes,
        completed_classes = EXCLUDED.completed_classes,
        cancelled_classes = EXCLUDED.cancelled_classes,
        num_users = EXCLUDED.num_users,
        associated_masterbatches = EXCLUDED.associated_masterbatches,
        source_updated_at = EXCLUDED.source_updated_at,
        silver_updated_at = now()
    RETURNING id
"""


def transform_class_id_lookup(database: Database) -> tuple[int, int]:
    with database.connection() as conn:
        cursor = conn.cursor()
        cursor.execute(_SELECT_SQL)
        rows = cursor.fetchall()

    rows_read = len(rows)
    values = []
    for row in rows:
        (
            batch_id, class_id, bundle_id, bundle_name, batch_name,
            tutor_id, tutor_name, total_classes, completed_classes,
            cancelled_classes, num_users, associated_masterbatches, received_at,
        ) = row

        values.append((
            str(batch_id).strip(),
            str(class_id).strip(),
            clean_text(bundle_id),
            clean_text(bundle_name),
            clean_text(batch_name),
            clean_text(tutor_id),
            clean_text(tutor_name),
            parse_int(total_classes),
            parse_int(completed_classes),
            parse_int(cancelled_classes),
            parse_int(num_users),
            clean_text(associated_masterbatches),
            received_at,
        ))

    if not values:
        return rows_read, 0

    with database.transaction() as conn:
        cursor = conn.cursor()
        returned = execute_values(cursor, _UPSERT_SQL, values, page_size=500, fetch=True)
        rows_written = len(returned)

    return rows_read, rows_written
