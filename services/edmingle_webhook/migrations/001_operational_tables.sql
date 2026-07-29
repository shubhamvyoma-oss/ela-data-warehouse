-- Optional operational deduplication table for the production-compatible webhook.
--
-- This migration is safe for the existing live database because it does not
-- alter, rewrite, delete, or lock-rewrite public.webhook_events. The live write
-- contract remains:
--
--   public.webhook_events(source, received_at, raw_payload)
--
-- Apply only after approval. Enable usage with WEBHOOK_DEDUP_ENABLED=true.

CREATE TABLE IF NOT EXISTS public.webhook_event_dedup (
    dedup_key text PRIMARY KEY,
    event_id text,
    webhook_event_id integer REFERENCES public.webhook_events(id) ON DELETE SET NULL,
    source text NOT NULL DEFAULT 'edmingle',
    first_seen_at timestamp without time zone NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_webhook_event_dedup_event_id
    ON public.webhook_event_dedup (event_id)
    WHERE event_id IS NOT NULL;

COMMENT ON TABLE public.webhook_event_dedup IS
    'Optional operational deduplication table. Authoritative raw payloads remain in public.webhook_events.';
