# Webhook Service

Production-compatible Edmingle webhook service for the Vyoma data warehouse.

This component replaces the legacy Flask webhook receiver in a staged migration. It preserves the verified live contract:

- Port: `5100`
- `GET /health` returns `{"status":"running"}`
- `GET /edmingle/webhook` returns `{"status":"ok"}`
- `OPTIONS /edmingle/webhook` returns `{"status":"ok"}` for validator compatibility
- `POST /edmingle/webhook` receives events
- `POST /webhook` is an optional compatibility alias
- `/edmingle/webhook` accepts both forms with and without a trailing slash
- Successful writes use `bronze.webhook_events(pipeline_run_id, source, received_at, raw_payload)`
  (updated 2026-09-23 -- see docs/database.md for the full history; was `public.webhook_events`
  before the live write path was redirected into the parent warehouse project's own Bronze layer)

The HTTP request path stores the full JSON payload directly into Bronze (see docs/database.md);
Silver routing/reconciliation for this data is still a downstream boundary, same as every other
Bronze table in the parent warehouse project.

## Runtime

```bash
docker compose build
docker compose up -d webhook replay
```

The container installs dependencies directly from `requirements.txt`. Do not create a Python virtual environment inside the Docker image.

## Configuration

Copy `.env.example` to `.env` and fill environment-specific values outside source control.

Important defaults:

| Variable | Default | Purpose |
| --- | --- | --- |
| `WEBHOOK_AUTH_MODE` | `disabled` | Compatibility mode for unsigned current production requests |
| `WEBHOOK_SCHEMA_NAME` | `public` | Live schema |
| `WEBHOOK_TABLE_NAME` | `webhook_events` | Live table |
| `WEBHOOK_DEDUP_ENABLED` | `false` | Optional dedup migration gate |
| `WEBHOOK_TOTAL_FAILURE_STATUS` | `503` | Response code when both DB insert and durable queue write fail; allowed values are `500` and `503` |
| `DATA_DIRECTORY` | `/app/data` | Persistent queue root |
| `LOG_DIRECTORY` | `/app/logs` | Persistent logs |

## Queue

The Docker configuration prepares persistent storage for:

- `/app/data/buffer`
- `/app/data/buffer/.processing`
- `/app/data/failed`
- `/app/data/archive`

Do not deploy new production volumes until approved.

Replay workers atomically claim pending queue files by moving them into `.processing`. Stale claims older than `QUEUE_CLAIM_TIMEOUT_SECONDS` are returned to `buffer`.

## Database

The live raw event table remains authoritative:

```sql
bronze.webhook_events(pipeline_run_id, source, received_at, raw_payload)
```

The optional migration `migrations/001_operational_tables.sql` creates deduplication metadata only. It does not alter or rewrite `bronze.webhook_events`.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

Tests use mocks and temporary directories unless explicitly marked otherwise. Do not run destructive outage tests against production.
