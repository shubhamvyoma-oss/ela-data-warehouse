-- Migration 012: silver.enrollments -- merges bronze.enrollment_reports
-- (historical CSV/API export) with live transaction.user_purchase_completed
-- events already flowing into bronze.webhook_events.
-- Forward-only. Do not edit 001-011.
--
-- Per project-owner decision: a NEW table, not a fold into the existing
-- silver.enrollment_reports (which stays exactly as-is, untouched, CSV/API
-- source only). Both sources describe the same underlying concept
-- (enrollment_id) but are largely non-overlapping in fields -- the CSV export
-- has enrollment_status/learner_type/registration_number/platform_type;
-- the webhook has installment/pricing/master_batch fields -- so this table
-- unions both column sets rather than picking one source as authoritative.
--
-- Column ownership (see processing/silver/enrollments.py for the exact
-- upsert semantics):
--   - "shared identity" fields (user_id, name, email, contact_number,
--     bundle_id, enrollment_expiration_date) are owned by whichever source
--     has data for a given enrollment_id; the webhook transform's own pass
--     always wins when both sources cover the same enrollment_id, since a
--     live purchase event is fresher than a periodic historical export.
--   - CSV-only fields are owned by the enrollment_reports pass and are
--     never touched by the webhook pass.
--   - webhook-only fields are owned by the webhook pass and are never
--     touched by the enrollment_reports pass.
-- has_enrollment_report / has_webhook_transaction record which source(s)
-- have ever contributed to a given row.

BEGIN;

CREATE TABLE IF NOT EXISTS silver.enrollments (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    enrollment_id text NOT NULL,

    -- Shared identity fields -- webhook wins when both sources have data.
    user_id text,
    name text,
    email text,
    contact_number text,
    bundle_id text,
    enrollment_expiration_date date,

    -- enrollment_reports (CSV/API)-only fields.
    enrollment_day date,
    contact_number_country_id text,
    state text,
    registration_number text,
    learner_type text,
    enrollment_mode text,
    enrollment_status text,
    bundle_name text,
    batch_ids text,
    batches text,
    product_type text,
    product_type_label text,
    platform_type text,
    preferred_categories text,

    -- webhook transaction-only fields.
    role text,
    currency text,
    discount numeric,
    course_name text,
    final_price numeric,
    portal_name text,
    original_price numeric,
    credits_applied numeric,
    enrollment_date timestamp with time zone,
    master_batch_id text,
    master_batch_name text,
    installment_name text,
    installment_amount numeric,
    institution_bundle_id text,
    contact_number_dial_code text,
    start_date date,
    end_date date,
    transaction_event_ts timestamp with time zone,

    -- Provenance.
    has_enrollment_report boolean NOT NULL DEFAULT false,
    has_webhook_transaction boolean NOT NULL DEFAULT false,

    source_updated_at timestamp with time zone,
    silver_updated_at timestamp with time zone NOT NULL DEFAULT now(),
    UNIQUE (enrollment_id)
);
COMMENT ON TABLE silver.enrollments IS 'Merges bronze.enrollment_reports (historical CSV/API export) with live transaction.user_purchase_completed events from bronze.webhook_events, keyed on enrollment_id. See processing/silver/enrollments.py for the exact column-ownership/precedence rules. Distinct from silver.enrollment_reports, which is unchanged (CSV/API source only).';

CREATE INDEX IF NOT EXISTS idx_silver_enrollments_user_id ON silver.enrollments (user_id);

INSERT INTO system.pipelines (pipeline_name, description, is_enabled)
VALUES
    ('silver_enrollments', 'silver_enrollments -> silver.enrollments (merges bronze.enrollment_reports with live transaction webhook events from bronze.webhook_events)', true)
ON CONFLICT (pipeline_name) DO UPDATE SET
    description = EXCLUDED.description;

COMMIT;
