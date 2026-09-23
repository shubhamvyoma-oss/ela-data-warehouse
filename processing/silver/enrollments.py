"""Silver transform: merges bronze.enrollment_reports (historical CSV/API
export) with live transaction.user_purchase_completed events from
bronze.webhook_events into silver.enrollments, keyed on enrollment_id.

Two independent upsert passes, run every time this transform executes
(see migration 009_silver_courses.sql-style precedent, applied here to
migration 012_silver_enrollments.sql):

1. `_upsert_from_enrollment_reports` -- owns enrollment_reports-only columns
   (state, learner_type, registration_number, platform_type, ...) plus sets
   the shared identity columns (user_id, name, email, contact_number,
   bundle_id, enrollment_expiration_date) only when first creating a row.
   On conflict (row already exists), it never touches shared identity
   columns -- a later webhook pass may have already refreshed them with
   live data, and this pass must not clobber that.
2. `_upsert_from_webhook_transactions` -- owns webhook-only columns
   (installment/pricing/master_batch fields) and *always* refreshes the
   shared identity columns on conflict, since a live purchase event is
   fresher than a periodic historical export.

Running both passes in this order every time means: whichever source last
touched an enrollment_id's shared identity fields is always the freshest
one, without needing to track per-field timestamps.
"""
from __future__ import annotations

from datetime import datetime

from psycopg2.extras import execute_values

from processing.silver._normalize import (
    DMY_FIRST_DATE_FORMATS,
    clean_email,
    clean_phone,
    clean_text,
    parse_date,
    parse_epoch_seconds,
    parse_numeric,
    upper_or_none,
)
from shared.database import Database

_TRANSACTION_EVENT_NAME = "transaction.user_purchase_completed"

_SELECT_REPORTS_SQL = """
    SELECT enrollment_id, enrollment_day, user_id, name, email, contact_number,
           contact_number_country_id, state, registration_number, learner_type,
           enrollment_mode, enrollment_status, bundle_id, bundle_name, batch_ids,
           batches, product_type, product_type_label, platform_type,
           enrollment_expiration_date, preferred_categories, received_at
    FROM bronze.enrollment_reports
    WHERE enrollment_id IS NOT NULL
"""

_UPSERT_REPORTS_SQL = """
    INSERT INTO silver.enrollments (
        enrollment_id, user_id, name, email, contact_number, bundle_id,
        enrollment_expiration_date, enrollment_day, contact_number_country_id,
        state, registration_number, learner_type, enrollment_mode,
        enrollment_status, bundle_name, batch_ids, batches, product_type,
        product_type_label, platform_type, preferred_categories,
        has_enrollment_report, source_updated_at
    ) VALUES %s
    ON CONFLICT (enrollment_id) DO UPDATE SET
        enrollment_day = EXCLUDED.enrollment_day,
        contact_number_country_id = EXCLUDED.contact_number_country_id,
        state = EXCLUDED.state,
        registration_number = EXCLUDED.registration_number,
        learner_type = EXCLUDED.learner_type,
        enrollment_mode = EXCLUDED.enrollment_mode,
        enrollment_status = EXCLUDED.enrollment_status,
        bundle_name = EXCLUDED.bundle_name,
        batch_ids = EXCLUDED.batch_ids,
        batches = EXCLUDED.batches,
        product_type = EXCLUDED.product_type,
        product_type_label = EXCLUDED.product_type_label,
        platform_type = EXCLUDED.platform_type,
        preferred_categories = EXCLUDED.preferred_categories,
        has_enrollment_report = true,
        silver_updated_at = now()
    RETURNING id
"""

_SELECT_WEBHOOK_SQL = """
    SELECT
        raw_payload->'payload'->>'enrollment_id' AS enrollment_id,
        raw_payload->'payload'->>'user_id' AS user_id,
        raw_payload->'payload'->>'name' AS name,
        raw_payload->'payload'->>'email' AS email,
        raw_payload->'payload'->>'contact_number' AS contact_number,
        raw_payload->'payload'->>'bundle_id' AS bundle_id,
        raw_payload->'payload'->>'enrollment_expiration_date' AS enrollment_expiration_date,
        raw_payload->'payload'->>'role' AS role,
        raw_payload->'payload'->>'currency' AS currency,
        raw_payload->'payload'->>'discount' AS discount,
        raw_payload->'payload'->>'course_name' AS course_name,
        raw_payload->'payload'->>'final_price' AS final_price,
        raw_payload->'payload'->>'portal_name' AS portal_name,
        raw_payload->'payload'->>'original_price' AS original_price,
        raw_payload->'payload'->>'credits_applied' AS credits_applied,
        raw_payload->'payload'->>'enrollment_date' AS enrollment_date,
        raw_payload->'payload'->>'master_batch_id' AS master_batch_id,
        raw_payload->'payload'->>'master_batch_name' AS master_batch_name,
        raw_payload->'payload'->>'installment_name' AS installment_name,
        raw_payload->'payload'->>'installment_amount' AS installment_amount,
        raw_payload->'payload'->>'institution_bundle_id' AS institution_bundle_id,
        raw_payload->'payload'->>'contact_number_dial_code' AS contact_number_dial_code,
        raw_payload->'payload'->>'start_date' AS start_date,
        raw_payload->'payload'->>'end_date' AS end_date,
        raw_payload->'event'->>'event_ts' AS event_ts,
        received_at
    FROM bronze.webhook_events
    WHERE raw_payload->'event'->>'event' = %(event_name)s
      AND raw_payload->'payload'->>'enrollment_id' IS NOT NULL
    ORDER BY received_at
"""

_UPSERT_WEBHOOK_SQL = """
    INSERT INTO silver.enrollments (
        enrollment_id, user_id, name, email, contact_number, bundle_id,
        enrollment_expiration_date, role, currency, discount, course_name,
        final_price, portal_name, original_price, credits_applied,
        enrollment_date, master_batch_id, master_batch_name, installment_name,
        installment_amount, institution_bundle_id, contact_number_dial_code,
        start_date, end_date, transaction_event_ts, has_webhook_transaction,
        source_updated_at
    ) VALUES %s
    ON CONFLICT (enrollment_id) DO UPDATE SET
        user_id = EXCLUDED.user_id,
        name = EXCLUDED.name,
        email = EXCLUDED.email,
        contact_number = EXCLUDED.contact_number,
        bundle_id = EXCLUDED.bundle_id,
        enrollment_expiration_date = EXCLUDED.enrollment_expiration_date,
        role = EXCLUDED.role,
        currency = EXCLUDED.currency,
        discount = EXCLUDED.discount,
        course_name = EXCLUDED.course_name,
        final_price = EXCLUDED.final_price,
        portal_name = EXCLUDED.portal_name,
        original_price = EXCLUDED.original_price,
        credits_applied = EXCLUDED.credits_applied,
        enrollment_date = EXCLUDED.enrollment_date,
        master_batch_id = EXCLUDED.master_batch_id,
        master_batch_name = EXCLUDED.master_batch_name,
        installment_name = EXCLUDED.installment_name,
        installment_amount = EXCLUDED.installment_amount,
        institution_bundle_id = EXCLUDED.institution_bundle_id,
        contact_number_dial_code = EXCLUDED.contact_number_dial_code,
        start_date = EXCLUDED.start_date,
        end_date = EXCLUDED.end_date,
        transaction_event_ts = EXCLUDED.transaction_event_ts,
        has_webhook_transaction = true,
        source_updated_at = EXCLUDED.source_updated_at,
        silver_updated_at = now()
    RETURNING id
"""


def _upsert_from_enrollment_reports(database: Database) -> tuple[int, int]:
    with database.connection() as conn:
        cursor = conn.cursor()
        cursor.execute(_SELECT_REPORTS_SQL)
        rows = cursor.fetchall()

    rows_read = len(rows)
    values = []
    for row in rows:
        (
            enrollment_id, enrollment_day, user_id, name, email, contact_number,
            contact_number_country_id, state, registration_number, learner_type,
            enrollment_mode, enrollment_status, bundle_id, bundle_name, batch_ids,
            batches, product_type, product_type_label, platform_type,
            enrollment_expiration_date, preferred_categories, received_at,
        ) = row

        values.append((
            str(enrollment_id).strip(),
            clean_text(user_id),
            clean_text(name),
            clean_email(email),
            clean_phone(contact_number),
            clean_text(bundle_id),
            parse_date(enrollment_expiration_date, DMY_FIRST_DATE_FORMATS),
            parse_date(enrollment_day, DMY_FIRST_DATE_FORMATS),
            clean_text(contact_number_country_id),
            clean_text(state),
            clean_text(registration_number),
            clean_text(learner_type),
            clean_text(enrollment_mode),
            upper_or_none(enrollment_status),
            clean_text(bundle_name),
            clean_text(batch_ids),
            clean_text(batches),
            clean_text(product_type),
            clean_text(product_type_label),
            clean_text(platform_type),
            clean_text(preferred_categories),
            True,
            received_at,
        ))

    if not values:
        return rows_read, 0

    with database.transaction() as conn:
        cursor = conn.cursor()
        returned = execute_values(cursor, _UPSERT_REPORTS_SQL, values, page_size=500, fetch=True)
        rows_written = len(returned)

    return rows_read, rows_written


def _upsert_from_webhook_transactions(database: Database) -> tuple[int, int]:
    with database.connection() as conn:
        cursor = conn.cursor()
        cursor.execute(_SELECT_WEBHOOK_SQL, {"event_name": _TRANSACTION_EVENT_NAME})
        rows = cursor.fetchall()

    rows_read = len(rows)
    # bronze.webhook_events has no uniqueness constraint on enrollment_id --
    # duplicate/retried deliveries (pre-dating dedup being enabled) or
    # multiple genuine installment-payment transactions can share one. A
    # single INSERT ... ON CONFLICT statement can't resolve the same
    # conflict key twice within itself, so this keeps only the most recent
    # row per enrollment_id (rows arrive pre-sorted by received_at) before
    # upserting.
    by_enrollment_id: dict[str, tuple] = {}
    for row in rows:
        (
            enrollment_id, user_id, name, email, contact_number, bundle_id,
            enrollment_expiration_date, role, currency, discount, course_name,
            final_price, portal_name, original_price, credits_applied,
            enrollment_date, master_batch_id, master_batch_name, installment_name,
            installment_amount, institution_bundle_id, contact_number_dial_code,
            start_date, end_date, event_ts, received_at,
        ) = row

        by_enrollment_id[str(enrollment_id).strip()] = ((
            str(enrollment_id).strip(),
            clean_text(user_id),
            clean_text(name),
            clean_email(email),
            clean_phone(contact_number),
            clean_text(bundle_id),
            _epoch_date(enrollment_expiration_date),
            clean_text(role),
            clean_text(currency),
            parse_numeric(discount),
            clean_text(course_name),
            parse_numeric(final_price),
            clean_text(portal_name),
            parse_numeric(original_price),
            parse_numeric(credits_applied),
            parse_epoch_seconds(enrollment_date),
            clean_text(master_batch_id),
            clean_text(master_batch_name),
            clean_text(installment_name),
            parse_numeric(installment_amount),
            clean_text(institution_bundle_id),
            clean_text(contact_number_dial_code),
            _epoch_date(start_date),
            _epoch_date(end_date),
            _iso_datetime(event_ts),
            True,
            received_at,
        ))

    values = list(by_enrollment_id.values())
    if not values:
        return rows_read, 0

    with database.transaction() as conn:
        cursor = conn.cursor()
        returned = execute_values(cursor, _UPSERT_WEBHOOK_SQL, values, page_size=500, fetch=True)
        rows_written = len(returned)

    return rows_read, rows_written


def _epoch_date(value: object):
    parsed = parse_epoch_seconds(value)
    return parsed.date() if parsed else None


def _iso_datetime(value: object):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def transform_enrollments(database: Database) -> tuple[int, int]:
    reports_read, reports_written = _upsert_from_enrollment_reports(database)
    webhook_read, webhook_written = _upsert_from_webhook_transactions(database)
    return reports_read + webhook_read, reports_written + webhook_written
