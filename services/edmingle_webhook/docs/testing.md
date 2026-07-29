# Testing

This document describes how to test the current implementation and where coverage should expand.

## Current Test Suite

The repository currently includes unit tests for:

| File | Coverage |
| --- | --- |
| `tests/test_auth.py` | Shared-secret auth, invalid secret rejection, HMAC auth |
| `tests/test_validation.py` | Valid JSON, malformed JSON, non-JSON content type |
| `tests/test_queue.py` | JSONL queue write/read and queue stats |
| `tests/test_routes.py` | Endpoint compatibility, invalid-payload no-op behavior, database/queue response decisions |
| `tests/test_replay.py` | Replay success, retry, dead-letter, atomic claiming, stale claim recovery, corrupt queue files |
| `tests/test_webhook_service.py` | Store orchestration, queue fallback, duplicate handling, concurrent duplicate handling |

Run tests:

```bash
pip install -r requirements-dev.txt
pytest
```

Run syntax validation:

```bash
python -m compileall -q .
```

## Unit Tests

Unit tests should avoid real network and database dependencies unless the behavior specifically requires integration coverage.

Recommended unit coverage additions:

- Missing body rejection.
- Invalid UTF-8 rejection.
- Payload size rejection.
- JSON array rejection.
- Dedup key hash fallback.
- HMAC timestamp expiry.
- HMAC nonce replay rejection.
- Rate limiter window behavior.
- Metrics counter and gauge formatting.
- Health checker filesystem failure handling.

## Integration Tests

Integration tests should use a disposable PostgreSQL database. They should verify:

- Migration applies cleanly.
- Migration is idempotent.
- New event inserts into `webhook_event_dedup` and `webhook_events`.
- Duplicate event does not create a second `webhook_events` row.
- Transaction rollback leaves no partial dedup row when event insertion fails.
- `/ready` fails when PostgreSQL is unavailable and succeeds when it is restored.

## Queue Testing

Queue tests should verify:

- Atomic write path creates only `.jsonl` files on success.
- Queue records preserve payload JSON, event id, source, timestamp, and request id.
- Attempt counter increments without corrupting JSONL.
- Archive and failed moves preserve file contents.
- Queue stats count pending, failed, archive, and byte size correctly.

## Replay Testing

Replay tests should verify:

- Files are processed oldest first by filename.
- Successful replay archives files.
- Duplicate replay archives files and increments duplicate metrics.
- Failed replay increments attempts.
- Files move to `data/failed` after `REPLAY_MAX_ATTEMPTS`.
- Corrupted queue records are handled without stopping the entire batch.

## Failure Simulation

Failure simulation should cover:

| Scenario | Expected result |
| --- | --- |
| PostgreSQL unavailable | Accepted webhook is queued |
| PostgreSQL restored | Replay drains queue into `webhook_events` |
| Queue directory unwritable | Request returns failure after DB failure |
| Disk nearly full | `/ready` reports unhealthy |
| Replay worker receives SIGTERM | Worker stops after current loop |
| Duplicate webhook | No second authoritative event row |

## Load Testing

Load tests should be run only against non-production environments unless explicitly approved.

Measure:

- Request latency.
- Database insert rate.
- Queue write rate during simulated database outage.
- Replay drain rate.
- Disk growth under outage.
- CPU and memory usage.

Do not tune pool sizes, worker counts, or replay batch size without measurements.

## Recovery Testing

At least once before production cutover, test:

1. Start webhook and replay worker.
2. Stop PostgreSQL.
3. Send test webhooks.
4. Confirm responses are `queued`.
5. Confirm files exist in `data/buffer`.
6. Restart PostgreSQL.
7. Confirm replay archives files.
8. Confirm rows exist in `public.webhook_events`.
9. Confirm queue depth returns to zero.
