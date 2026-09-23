# Database

**Updated 2026-09-23.** The live write path was redirected from `public.webhook_events`
to `bronze.webhook_events`, bringing this service's live event stream into the parent
warehouse project's own Bronze layer (see `../../database/migrations/011_bronze_webhook_events.sql`
and `../../ROADMAP.md`). Historical rows from `public.webhook_events` (this database's own
copy, and the separate standalone `webhook_db` database's copy) were backfilled into
`bronze.webhook_events` first -- see `../../database/backfill_bronze_webhook_events.py`.
`public.webhook_events` itself was **not** dropped, altered, or truncated -- its rows remain
exactly as they were, just no longer written to by this service going forward. The sections
below describe the *current* (post-redirect) behavior; historical context is noted where it
matters.

## Authoritative Event Table

The service writes successful webhook events into:

```sql
bronze.webhook_events
```

Schema (see migration `011_bronze_webhook_events.sql` in the parent warehouse project for
the authoritative definition):

```sql
CREATE TABLE bronze.webhook_events (
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
```

`legacy_source_database`/`legacy_source_id` are only ever set by the one-time historical
backfill (identifying which original table + row a backfilled event came from, and making
the backfill script safely re-runnable via `ON CONFLICT DO NOTHING`). Every row this service
inserts live leaves both NULL.

Every row also requires a `pipeline_run_id`, linking it to an `audit.pipeline_runs` entry --
`app/database/pool.py` creates one per webhook event (`run_type='streaming'`, already
`SUCCESS`/finished in the same transaction as the Bronze insert, since a single webhook
insert has no meaningful "in-progress" state the way a multi-step collector run does).

Rules (carried forward from before the redirect, still true, just naming the current table):

- Do not create a second primary webhook event table.
- Do not drop, truncate, rename, or recreate `bronze.webhook_events`.
- Keep successful webhook payloads in `raw_payload`.
- Keep changes backward compatible for existing consumers.

**Historical note:** before 2026-09-23, this service wrote into `public.webhook_events`
(schema: `id integer, source text, received_at timestamp without time zone, raw_payload
jsonb`). That table and its rows are untouched -- they're just no longer the live write
target.

## Supporting Deduplication Table

Migration `migrations/001_operational_tables.sql` creates:

```sql
CREATE TABLE IF NOT EXISTS public.webhook_event_dedup (
    dedup_key text PRIMARY KEY,
    event_id text,
    webhook_event_id bigint REFERENCES bronze.webhook_events(id) ON DELETE SET NULL,
    source text NOT NULL DEFAULT 'edmingle',
    first_seen_at timestamp without time zone NOT NULL
);
```

This table is operational metadata. It is not the event source of truth. It was never
applied before the write-path redirect, so its `webhook_event_id` FK was updated to point
at `bronze.webhook_events(id)` directly -- there was no existing wrong-target constraint to
migrate away from.

## Indexes and Constraints

| Object | Purpose |
| --- | --- |
| `webhook_events_pkey` | Primary key on `bronze.webhook_events.id` |
| `idx_bronze_webhook_events_received_at` | Supports time-range queries |
| `webhook_events_legacy_source_database_legacy_source_id_key` | Idempotent backfill re-runs |
| `webhook_event_dedup_pkey` | Prevents duplicate `dedup_key` values |
| `idx_webhook_event_dedup_event_id` | Supports lookup by upstream `event_id` when present |
| FK to `bronze.webhook_events(id)` | Links dedup record to inserted event without owning the payload |

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

No returned row means duplicate. The application rolls back and does not insert a second row into `bronze.webhook_events`.

When `WEBHOOK_DEDUP_ENABLED=false` (the default), the service inserts every accepted request into `bronze.webhook_events`.

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

- Back up `bronze.webhook_events` before applying migrations affecting it.
- Prefer `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS`.
- Avoid destructive operations.
- Avoid table rewrites and long blocking locks where practical.
- Keep rollback scripts explicit.

Apply current migration (optional dedup table -- not required for normal operation):

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/001_operational_tables.sql
```

Rollback current supporting table:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/001_operational_tables_rollback.sql
```

Rollback removes dedup metadata. It does not remove payload rows from `bronze.webhook_events`.

`bronze.webhook_events` itself is created and owned by the parent warehouse project's own
migration (`../../database/migrations/011_bronze_webhook_events.sql`), not by anything in
this service's own `migrations/` folder.

## Future Schema Evolution

Future schema changes should follow these rules:

- Add supporting tables for operational state.
- Add columns to `bronze.webhook_events` only when payload storage truly requires it, and
  coordinate with the parent warehouse project's own migration numbering.
- Keep new columns nullable or default-safe for existing rows.
- Add indexes only for proven query paths.
- Document every migration in this file and `CHANGELOG.md`.
