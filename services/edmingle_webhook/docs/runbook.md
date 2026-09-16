# Runbook

This runbook is for operating the upgraded Docker webhook implementation after it has been approved and deployed.

## Quick Checks

```bash
docker compose ps
curl -fsS http://127.0.0.1:5100/live
curl -fsS http://127.0.0.1:5100/health
curl -fsS http://127.0.0.1:5100/ready
curl -fsS http://127.0.0.1:5100/metrics
```

Useful paths inside the container:

| Path | Purpose |
| --- | --- |
| `/app/data/buffer` | Pending replay files |
| `/app/data/failed` | Files that exceeded replay attempts |
| `/app/data/archive` | Replayed or duplicate files |
| `/app/logs` | Application logs |

## Database Down

Symptoms:

- `/ready` returns unhealthy.
- Responses from `POST /edmingle/webhook` may return `queued`.
- `webhook_database_failures_total` increases.
- Files appear in `data/buffer`.

Procedure:

1. Confirm PostgreSQL status from the database host.
2. Check application logs:

   ```bash
   docker compose logs webhook
   docker compose logs replay
   ```

3. Check queue depth:

   ```bash
   curl -fsS http://127.0.0.1:5100/metrics | grep webhook_queue_depth
   ```

4. Restore PostgreSQL connectivity.
5. Let the replay worker drain the queue or run:

   ```bash
   docker compose run --rm replay python scripts/replay_once.py
   ```

6. Verify queue depth returns to zero.

## Replay Queue Growing

Symptoms:

- `webhook_queue_depth` increases over time.
- Files accumulate in `data/buffer`.
- `logs/replay.log` contains replay failures.

Procedure:

1. Verify the replay container is running.
2. Check `/ready`; replay cannot drain while PostgreSQL is unavailable.
3. Inspect replay logs.
4. Check free disk space.
5. Run one replay cycle manually and inspect output:

   ```bash
   docker compose run --rm replay python scripts/replay_once.py
   ```

6. Do not purge queue files unless the payloads have been safely stored or explicitly accepted as unrecoverable.

## Webhook Failures

Symptoms:

- HTTP 400, 401, 413, 415, 429, or 503 responses.

Response meanings:

| Status | Meaning |
| --- | --- |
| `400` | Reserved for future strict validation. Compatibility-mode malformed/empty/non-object JSON currently returns `200 {"status":"ok"}` without insert or queue. |
| `401` | Authentication failed |
| `413` | Payload exceeds `MAX_PAYLOAD_BYTES` |
| `415` | Content type is not JSON |
| `429` | In-process rate limit exceeded |
| `503` | Database insert failed and queue write also failed |

Procedure:

1. Check request headers and payload shape.
2. Check `logs/errors.log` and `logs/security.log`.
3. Check disk writability if responses are `503`.
4. Confirm the client sends the configured authentication mechanism.

Compatibility note: empty bodies, malformed JSON, JSON `null`, and JSON arrays return `200 {"status":"ok"}` during the live compatibility phase. They are logged as ignored requests and are not inserted or queued.

`WEBHOOK_TOTAL_FAILURE_STATUS` controls the response when both database insert and durable queue write fail. The default is `503`; `500` is allowed if operations require the old total-failure status.

## Authentication Failures

Symptoms:

- `401 unauthorized`.
- `webhook_authentication_failures_total` increases.

Procedure:

1. Confirm `WEBHOOK_AUTH_MODE` is `shared_secret` or `hmac`. The compatibility default is `disabled`.
2. Confirm `WEBHOOK_SHARED_SECRET` or `WEBHOOK_HMAC_SECRET` is set in the running container for the selected mode.
3. Confirm header names:

   ```text
   WEBHOOK_SHARED_SECRET_HEADER
   WEBHOOK_HMAC_SIGNATURE_HEADER
   WEBHOOK_HMAC_TIMESTAMP_HEADER
   WEBHOOK_HMAC_NONCE_HEADER
   ```

4. For HMAC, confirm the signature payload is `timestamp + "." + raw_body`.
5. Check clock skew; HMAC timestamps must be within `WEBHOOK_SIGNATURE_TOLERANCE_SECONDS`.

## High Error Rate

Procedure:

1. Check `/metrics` counters.
2. Group errors by status code from reverse proxy or application logs.
3. Check database health.
4. Check disk health.
5. Check recent deployment or configuration changes.
6. If queue depth grows rapidly, preserve the queue volume before restarting services.

## Container Restart

Procedure:

1. Check current status:

   ```bash
   docker compose ps
   ```

2. Review recent logs:

   ```bash
   docker compose logs --tail=200 webhook
   docker compose logs --tail=200 replay
   ```

3. Verify persistent volumes are still mounted.
4. Check `/health` and `/ready`.
5. Check queue depth.

Expected behavior:

- Queue files survive restarts if `/app/data` is persistent.
- Metrics reset after restart.
- HMAC nonce memory resets after restart.

## Disk Full

Symptoms:

- `/ready` reports low disk.
- Queue writes may fail.
- Logs may stop rotating or writing.

Procedure:

1. Check disk usage:

   ```bash
   df -h
   du -sh /path/to/webhook/data/*
   du -sh /path/to/webhook/logs/*
   ```

2. Preserve `data/buffer` and `data/failed`.
3. Archive or move old `data/archive` files if they are no longer operationally needed.
4. Compress or rotate logs externally if necessary.
5. Increase volume size if queue growth is legitimate.

Do not delete `data/buffer` unless every event has been confirmed stored or explicitly accepted as lost.

## Log Rotation

Application log files rotate by size and compress rotated files. If logs grow unexpectedly:

1. Check `LOG_MAX_BYTES` and `LOG_BACKUP_COUNT`.
2. Check whether noisy errors are repeating.
3. Confirm `/app/logs` is mounted to persistent storage.
4. Use external log shipping if long retention is required.

## Alert Handling

No alerting framework exists in this service (a previously unused AlertManager module was removed as dead code -- see ROADMAP.md). Operational alerting should be based on:

- Reverse proxy or uptime checks on `/ready`.
- Metrics scraping.
- Container restart monitoring.
- Log monitoring.
- Disk usage monitoring.

## Recovery Procedures

### Drain Pending Queue

```bash
docker compose run --rm replay python scripts/replay_once.py
```

Repeat until `webhook_queue_depth` is zero, or let `scripts/replay_worker.py` continue running.

### Retry Failed Files

1. Inspect files in `data/failed`.
2. Confirm why they failed.
3. If retry is appropriate, move selected files back to `data/buffer`.
4. Run replay.

### Disaster Recovery

1. Preserve database backups and queue volumes.
2. Restore PostgreSQL.
3. Restore `/app/data`.
4. Start `webhook` and `replay`.
5. Verify `/ready`.
6. Drain queue.
7. Confirm recent events exist in `public.webhook_events`.
