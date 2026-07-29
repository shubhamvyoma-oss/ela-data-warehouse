# Database

The database design preserves the existing production table and adds only operational metadata required by the new webhook service.

## Authoritative Event Table

The service writes successful webhook events into:

```sql
public.webhook_events
```

Known schema from the production audit:

```sql
CREATE TABLE public.webhook_events (
    id integer NOT NULL,
    source text,
    received_at timestamp without time zone,
    raw_payload jsonb
);

ALTER TABLE ONLY public.webhook_events
    ADD CONSTRAINT webhook_events_pkey PRIMARY KEY (id);
```

Rules:

- Do not replace this table.
- Do not create a new primary webhook event table.
- Do not drop, truncate, rename, or recreate this table.
- Keep successful webhook payloads in `raw_payload`.
- Keep changes backward compatible for existing consumers.

## Supporting Deduplication Table

Migration `migrations/001_operational_tables.sql` creates:

```sql
CREATE TABLE IF NOT EXISTS public.webhook_event_dedup (
    dedup_key text PRIMARY KEY,
    event_id text,
    webhook_event_id integer REFERENCES public.webhook_events(id) ON DELETE SET NULL,
    source text NOT NULL DEFAULT 'edmingle',
    first_seen_at timestamp without time zone NOT NULL
);
```

This table is operational metadata. It is not the event source of truth.

## Indexes and Constraints

| Object | Purpose |
| --- | --- |
| `webhook_events_pkey` | Existing primary key on `webhook_events.id` |
| `webhook_event_dedup_pkey` | Prevents duplicate `dedup_key` values |
| `idx_webhook_event_dedup_event_id` | Supports lookup by upstream `event_id` when present |
| FK to `webhook_events(id)` | Links dedup record to inserted event without owning the payload |

The `event_id` index is partial and excludes nulls:

```sql
CREATE INDEX IF NOT EXISTS idx_webhook_event_dedup_event_id
    ON public.webhook_event_dedup (event_id)
    WHERE event_id IS NOT NULL;
```

Write trade-off: when enabled, the dedup table adds one insert and one update per new event, plus index maintenance. It is optional during the compatibility phase and avoids changing the authoritative payload table.

## Deduplication Strategy

`parse_webhook_request` builds a `dedup_key` as follows:

1. Use the first configured event id field found in the JSON body.
2. For nested Edmingle payloads, use an upstream nested id when present.
3. If the payload has `event.event` and `event.event_ts`, use `event_name:event_ts`.
4. If no reliable upstream identity exists, hash canonical JSON with SHA-256 using these fields: event name, event timestamp, live-mode flag, and the event payload/body.

Default event id fields:

```text
event_id,id,transaction_id,order_id
```

When `WEBHOOK_DEDUP_ENABLED=true`, the database insert first attempts:

```sql
INSERT INTO webhook_event_dedup (...)
ON CONFLICT (dedup_key) DO NOTHING
RETURNING dedup_key
```

No returned row means duplicate. The application rolls back and does not insert a second row into `webhook_events`.

When `WEBHOOK_DEDUP_ENABLED=false`, the service preserves the current live behavior and inserts every accepted request into `public.webhook_events`.

## Connection Pooling

`DatabasePool` uses `psycopg2.pool.ThreadedConnectionPool`.

Relevant settings:

| Variable | Purpose |
| --- | --- |
| `DB_POOL_MIN_CONNECTIONS` | Minimum pool connections |
| `DB_POOL_MAX_CONNECTIONS` | Maximum pool connections |
| `DB_CONNECT_TIMEOUT_SECONDS` | PostgreSQL connection timeout |
| `DB_STATEMENT_TIMEOUT_MS` | PostgreSQL statement timeout |
| `DB_RETRY_ATTEMPTS` | Insert retry attempts |
| `DB_RETRY_BACKOFF_MS` | Sleep between retry attempts |

Connections are opened lazily. `health_check` uses `SELECT 1`.

## Migration Strategy

Migrations must be production-safe:

- Back up `webhook_events` before applying migrations.
- Prefer `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS`.
- Avoid destructive operations.
- Avoid table rewrites and long blocking locks where practical.
- Keep rollback scripts explicit.

Apply current migration:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/001_operational_tables.sql
```

Rollback current supporting table:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/001_operational_tables_rollback.sql
```

Rollback removes dedup metadata. It does not remove payload rows from `webhook_events`.

## Future Schema Evolution

Future schema changes should follow these rules:

- Add supporting tables for operational state.
- Add columns to `webhook_events` only when payload storage truly requires it.
- Keep new columns nullable or default-safe for existing rows.
- Add indexes only for proven query paths.
- Document every migration in this file and `CHANGELOG.md`.
