# Webhook Service

Production-compatible Edmingle webhook service for the Vyoma data warehouse.

This component replaces the legacy Flask webhook receiver in a staged migration. It preserves the verified live contract:

- Port: `5100`
- `GET /health` returns `{"status":"running"}`
- `GET /edmingle/webhook` returns `{"status":"ok"}`
- `POST /edmingle/webhook` receives events
- `POST /webhook` is an optional compatibility alias
- Successful writes use `public.webhook_events(source, received_at, raw_payload)`

The HTTP request path stores the full JSON payload and does not route directly to Silver. Warehouse synchronization and Silver routing are downstream boundaries.

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
public.webhook_events(source, received_at, raw_payload)
```

The optional migration `migrations/001_operational_tables.sql` creates deduplication metadata only. It does not alter or rewrite `public.webhook_events`.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

Tests use mocks and temporary directories unless explicitly marked otherwise. Do not run destructive outage tests against production.
