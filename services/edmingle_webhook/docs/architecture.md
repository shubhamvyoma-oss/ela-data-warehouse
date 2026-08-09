# Architecture

This document describes the local upgraded Edmingle webhook service that is being validated as a production candidate.

## System Context

The service receives Edmingle LMS webhook events over HTTP and stores accepted payloads in PostgreSQL. It keeps compatibility with the existing webhook path:

```text
GET  /edmingle/webhook
POST /edmingle/webhook
POST /webhook
```

Validation also returns JSON for `OPTIONS /edmingle/webhook`, and the Edmingle
endpoint accepts both forms with and without a trailing slash. This prevents
third-party validation probes from receiving Flask's default empty or HTML
responses.

The existing `public.webhook_events` table remains the authoritative event store. The `/webhook` POST route is a compatibility alias that uses the same internal handler as `/edmingle/webhook`. A persistent JSONL queue protects accepted events during database outages.

## Runtime Components

```text
Docker Compose
  |
  +-- webhook service
  |     |
  |     +-- gunicorn
  |           |
  |           +-- Flask app from wsgi.py
  |
  +-- replay service
        |
        +-- python scripts/replay_worker.py
```

Both services use the same mounted data and log volumes.

## Application Composition

`app.main.create_app` creates shared application components and stores them in `flask_app.extensions`.

| Component | Class | Purpose |
| --- | --- | --- |
| Settings | `Settings` | Reads and validates environment configuration |
| Database | `DatabasePool` | Manages PostgreSQL pool and event inserts |
| Queue | `FileEventQueue` | Persists events to local JSONL files |
| Metrics | `MetricsRegistry` | Tracks in-memory counters, gauges, and latency |
| Rate limiter | `InMemoryRateLimiter` | Limits request rate per client key |
| Service | `WebhookService` | Orchestrates database insert and queue fallback |

## Request Lifecycle

```text
POST /edmingle/webhook
    |
    v
extract client address
    |
    v
rate-limit check
    |
    v
read raw request body
    |
    v
apply configured authentication mode
    |
    v
validate content type, body, size, UTF-8, JSON
    |
    v
build WebhookEvent
    |
    v
WebhookService.store_event
    |
    +-- insert into PostgreSQL
    |
    +-- enqueue JSONL file if database insert fails
```

Validation happens after authentication. For live compatibility, empty bodies, malformed JSON, JSON `null`, and JSON arrays are treated as validation no-ops: the service logs a structured warning, returns `200 {"status":"ok"}`, and does not insert or queue the request. Other unsupported request shapes should be reviewed before changing compatibility behavior.

## Database Lifecycle

`DatabasePool.insert_event` retries insertion according to `DB_RETRY_ATTEMPTS` and `DB_RETRY_BACKOFF_MS`.

The compatibility-phase insert writes only the live table contract:

```sql
INSERT INTO public.webhook_events (source, received_at, raw_payload)
VALUES (...)
```

When `WEBHOOK_DEDUP_ENABLED=true`, each insert runs in one transaction:

1. Insert `dedup_key` into `public.webhook_event_dedup`.
2. If the key already exists, roll back and return duplicate.
3. Insert payload into `public.webhook_events`.
4. Update `public.webhook_event_dedup.webhook_event_id`.
5. Commit.

If any step fails, the transaction rolls back. After all retry attempts fail, the caller queues the event.

## Queue Lifecycle

Queued events are stored as one JSONL file per event:

```text
data/
  buffer/   pending replay files
    .processing/ claimed files being processed
  failed/   exhausted replay files
  archive/  successfully replayed or duplicate files
```

Queue insertion:

1. Serialize `WebhookEvent` plus queue metadata.
2. Write to a temporary file with exclusive creation.
3. Flush and `fsync` the file.
4. Atomically rename the temp file into `data/buffer`.
5. On POSIX systems, `fsync` the directory.

This favors inspectability and crash safety over maximum throughput.

## Replay Lifecycle

`ReplayEngine.run_once` processes up to `REPLAY_BATCH_SIZE` files from `data/buffer`, sorted by filename. Before processing, each worker atomically renames a pending file into `data/buffer/.processing`. Only the worker that successfully claims the file may process it.

```text
data/buffer/*.jsonl
    |
    v
atomic rename to data/buffer/.processing/*.jsonl
    |
    v
read WebhookEvent
    |
    v
DatabasePool.insert_event
    |
    +-- inserted: move to data/archive
    +-- duplicate: move to data/archive
    +-- failed: increment attempts
              |
              +-- attempts < max: leave in data/buffer
              +-- attempts >= max: move to data/failed
```

Claimed files older than `QUEUE_CLAIM_TIMEOUT_SECONDS` are treated as abandoned and moved back to `data/buffer` before scanning pending files.

Unreadable queue files are moved directly to `data/failed`. A `.failure.json` sidecar records the original filename, failed filename, failure reason, detection timestamp, and file size without logging payload contents.

The long-running replay worker sleeps for `REPLAY_BACKOFF_SECONDS` between runs and handles `SIGTERM` and `SIGINT` by stopping the loop after the current cycle.

## Logging Architecture

`configure_logging` configures root logging plus separate named log files:

- `webhook.log`
- `errors.log`
- `replay.log`
- `database.log`
- `queue.log`
- `security.log`
- `startup.log`
- `health.log`
- `metrics.log`

Logs are JSON by default. File handlers rotate by size and compress rotated files with gzip.

## Monitoring Architecture

Health checks are synchronous:

| Endpoint | Checks |
| --- | --- |
| `/live` | Process responds |
| `/health` | Compatibility endpoint returning `{"status":"running"}` |
| `/ready` | Filesystem, log directory, queue, disk, and PostgreSQL readiness |
| `/metrics` | Prometheus text-format in-memory metrics |

Metrics reset on process restart because `MetricsRegistry` is in memory.

## Alerting Architecture

`app.notifications.providers.AlertManager` can send alert payloads to console logs, Slack, Discord, and Microsoft Teams webhook URLs. The current application code defines this framework but does not yet wire automatic alert dispatch into database, queue, replay, or security failure paths.

Operational procedures should rely on logs, health checks, and metrics until alert dispatch is integrated.

## Docker Architecture

The image uses:

- `python:3.12-slim`
- Direct dependency installation from `requirements.txt`
- Non-root `webhook` user
- `/app/data` and `/app/logs` directories owned by the runtime user
- Docker healthcheck calling `scripts/healthcheck.py`

No Python virtual environment is created in the image.

## Failure Recovery

| Failure | Current behavior |
| --- | --- |
| PostgreSQL insert fails | Event is queued to `data/buffer` after configured database retries |
| Replay insert fails | Attempt count increments; file remains pending until max attempts |
| Replay exceeds attempts | File moves to `data/failed` |
| Duplicate event arrives | Duplicate is detected by `webhook_event_dedup.dedup_key` when optional deduplication is enabled |
| Disk queue write fails | Request returns failure; service cannot guarantee local preservation |
| Process restarts | Queue files persist if `/app/data` is mounted |
| Metrics reset | Expected; metrics are in memory |

## Complexity Notes

| Operation | Complexity | Notes |
| --- | --- | --- |
| Request validation | O(n) | n is request body size |
| Queue insert | O(1) | One event file write and atomic rename |
| Dedup lookup | O(1) average | PostgreSQL primary key on `dedup_key` |
| Replay batch selection | O(k log k) | k is pending queue files because filenames are sorted |
| Queue stats | O(k) | Directory scans over queue files |
| Metrics update | O(1) | Lock-protected in-memory counters |
