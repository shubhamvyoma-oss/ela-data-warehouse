-- Migration 011: bronze.webhook_events
-- Forward-only. Do not edit 001-010.
--
-- Brings the webhook service's live event stream into the warehouse's own
-- Bronze layer, per project-owner decision. Distinct from public.webhook_events
-- (the webhook service's own storage, in the public schema -- see
-- tests/test_migrations.py, which deliberately asserts that table is never
-- created by these migrations): this table is new, Bronze-native, and follows
-- the same pipeline_run_id/audit lineage convention every other Bronze table
-- already uses.
--
-- Historical data from two sources is being backfilled into this table
-- (see scripts/backfill_bronze_webhook_events.py, run once, not part of this
-- migration):
--   1. webhook_db.public.webhook_events (the standalone legacy edmingle-webhook
--      project's own database -- a separate Postgres database entirely)
--   2. this database's own public.webhook_events (the current live webhook
--      service's storage, up to the moment the live write path is redirected
--      to insert into this table directly)
--
-- legacy_source_database/legacy_source_id record exactly where each
-- backfilled row came from, for traceability and to make the backfill script
-- safely re-runnable (ON CONFLICT DO NOTHING). Rows written by the live
-- service AFTER it's redirected to write here directly leave both columns
-- NULL -- Postgres never treats two NULLs as equal for UNIQUE purposes, so
-- that never blocks a live insert.

BEGIN;

CREATE TABLE IF NOT EXISTS bronze.webhook_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pipeline_run_id uuid NOT NULL REFERENCES audit.pipeline_runs(id),
    source text NOT NULL,
    received_at timestamp without time zone NOT NULL,
    raw_payload jsonb NOT NULL,
    legacy_source_database text,
    legacy_source_id bigint,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    UNIQUE (legacy_source_database, legacy_source_id)
);
COMMENT ON TABLE bronze.webhook_events IS 'Live Edmingle webhook events (transaction/purchase events, url.validate pings), promoted into Bronze. Backfilled from webhook_db.public.webhook_events and this database''s own public.webhook_events -- see legacy_source_database/legacy_source_id and scripts/backfill_bronze_webhook_events.py. Rows inserted after the live cutover have both legacy_source_* columns NULL.';

CREATE INDEX IF NOT EXISTS idx_bronze_webhook_events_received_at
    ON bronze.webhook_events (received_at);

INSERT INTO system.pipelines (pipeline_name, description, is_enabled)
VALUES
    ('webhook_ingestion', 'webhook_ingestion -> bronze.webhook_events (live Edmingle webhook events, pushed not pulled -- see services/edmingle_webhook)', true)
ON CONFLICT (pipeline_name) DO UPDATE SET
    description = EXCLUDED.description;

COMMIT;
