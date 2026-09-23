-- Migration 013: expression index for the transaction-event filter
-- processing/silver/enrollments.py runs every minute (see the cron job
-- documented in ROADMAP.md), so keeping its WHERE clause on
-- bronze.webhook_events cheap matters as that table keeps growing
-- indefinitely (it never gets pruned).
-- Forward-only. Do not edit 001-012.

BEGIN;

CREATE INDEX IF NOT EXISTS idx_bronze_webhook_events_transaction_event
    ON bronze.webhook_events (((raw_payload->'event'->>'event')))
    WHERE raw_payload->'payload'->>'enrollment_id' IS NOT NULL;

COMMIT;
