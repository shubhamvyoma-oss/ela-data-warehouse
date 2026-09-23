-- Optional operational deduplication table for the webhook service.
--
-- Updated 2026-09-23: the live write path was redirected from
-- public.webhook_events to bronze.webhook_events (see app/database/pool.py
-- and database/migrations/011_bronze_webhook_events.sql in the parent
-- warehouse project) as part of bringing the webhook's live event stream
-- into the warehouse's Bronze layer. webhook_event_id below now references
-- bronze.webhook_events(id), not public.webhook_events(id) -- this
-- migration was never applied before that redirect happened, so there was
-- no existing wrong-target constraint to migrate away from.
--
-- This migration is still safe for the live database: it does not alter,
-- rewrite, delete, or lock-rewrite bronze.webhook_events or any other
-- existing table.
--
-- Apply only after approval. Enable usage with WEBHOOK_DEDUP_ENABLED=true.

CREATE TABLE IF NOT EXISTS public.webhook_event_dedup (
    dedup_key text PRIMARY KEY,
    event_id text,
    webhook_event_id bigint REFERENCES bronze.webhook_events(id) ON DELETE SET NULL,
    source text NOT NULL DEFAULT 'edmingle',
    first_seen_at timestamp without time zone NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_webhook_event_dedup_event_id
    ON public.webhook_event_dedup (event_id)
    WHERE event_id IS NOT NULL;

COMMENT ON TABLE public.webhook_event_dedup IS
    'Optional operational deduplication table. Authoritative raw payloads remain in bronze.webhook_events.';
