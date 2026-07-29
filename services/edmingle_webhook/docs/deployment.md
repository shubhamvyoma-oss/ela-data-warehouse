# Deployment

This guide describes the planned production deployment process for the Docker-based webhook implementation.

## Deployment Model

```text
Reverse proxy
    |
    v
Docker service: webhook
    |
    +-- /app/data mounted volume
    +-- /app/logs mounted volume

Docker service: replay
    |
    +-- same /app/data mounted volume
    +-- same /app/logs mounted volume
```

The reverse proxy must continue routing Edmingle traffic to:

```text
POST /edmingle/webhook
```

Do not change the public endpoint without coordinating with Edmingle and downstream production users.

## Production Prerequisites

- Docker and Docker Compose installed.
- PostgreSQL reachable from the container network.
- Existing `public.webhook_events` table present.
- Persistent volume or bind mount for `/app/data`.
- Persistent volume or bind mount for `/app/logs`.
- Authentication values selected and configured.
- Reverse proxy route verified.

Do not guess production values. If any value is unknown, collect it from the server before deployment.

## Environment Setup

Create `.env` from `.env.example`:

```bash
cp .env.example .env
```

Fill required database values:

```text
DB_NAME=
DB_USER=
DB_PASSWORD=
DB_HOST=
DB_PORT=5432
```

Set `DATABASE_URL` for `pg_dump`, `psql`, and `scripts/apply_migration.sh` commands:

```text
DATABASE_URL=
```

Select the authentication mode:

```text
WEBHOOK_AUTH_MODE=disabled
WEBHOOK_SHARED_SECRET=
WEBHOOK_HMAC_SECRET=
```

Use `WEBHOOK_AUTH_MODE=disabled` for the initial compatibility phase because the verified live service does not enforce webhook authentication. Move to `shared_secret` or `hmac` only after confirming Edmingle sends the required headers.

Set `ADMIN_TOKEN` only if manual replay over HTTP is required.

## Backup Procedure

Before applying migrations or routing traffic to a new deployment:

```bash
pg_dump "$DATABASE_URL" --table=public.webhook_events --format=custom --file=webhook_events_before_deploy.dump
```

Also preserve queue volumes before replacing a running deployment:

```bash
docker compose stop webhook replay
docker run --rm -v edmingle_webhook_data:/data -v "$PWD:/backup" busybox tar czf /backup/webhook_data_backup.tgz /data
```

The production data volume name is `edmingle_webhook_data`.

## Migration Procedure

Apply the supporting deduplication table migration:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/001_operational_tables.sql
```

Verify:

```bash
psql "$DATABASE_URL" -c "\dt public.webhook_event_dedup"
psql "$DATABASE_URL" -c "SELECT count(*) FROM public.webhook_events;"
```

The migration does not alter, truncate, or replace `public.webhook_events`.

## Build and Start

```bash
docker compose build
docker compose up -d webhook replay
```

The Docker image installs dependencies directly from `requirements.txt`. It does not create or use a virtual environment inside the container.

## Health Verification

Check container status:

```bash
docker compose ps
```

Check endpoints:

```bash
curl -fsS http://127.0.0.1:5100/live
curl -fsS http://127.0.0.1:5100/health
curl -fsS http://127.0.0.1:5100/ready
curl -fsS http://127.0.0.1:5100/metrics
```

Expected:

- `/live` returns `200`.
- `/health` returns `{"status":"running"}` with HTTP 200 for production compatibility.
- `/ready` returns `200` only when PostgreSQL is reachable.
- `/metrics` returns Prometheus text format.

## Controlled Webhook Test

Use a non-production test payload. Add the configured authentication header only when `WEBHOOK_AUTH_MODE` is not `disabled`:

```bash
curl -i \
  -X POST http://127.0.0.1:5100/edmingle/webhook \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: $WEBHOOK_SHARED_SECRET" \
  --data '{"event_id":"deployment-test","event":"test"}'
```

Verify database insert:

```bash
psql "$DATABASE_URL" -c "SELECT id, source, received_at FROM public.webhook_events ORDER BY id DESC LIMIT 5;"
```

## Upgrade Procedure

1. Review `CHANGELOG.md`.
2. Review new migrations.
3. Back up `webhook_events` and queue volume.
4. Apply migrations.
5. Build the new image.
6. Start containers.
7. Verify health endpoints and metrics.
8. Send a controlled webhook.
9. Monitor logs and queue depth.

## Rollback Procedure

1. Stop new containers:

   ```bash
   docker compose stop webhook replay
   ```

2. Restore routing to the previous known-good webhook deployment.
3. Preserve `data/buffer` before removing any containers or volumes.
4. Only run rollback SQL if the supporting dedup table is no longer needed:

   ```bash
   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/001_operational_tables_rollback.sql
   ```

Rollback SQL does not delete rows from `webhook_events`.

## Production Checklist

- [ ] Production table schema verified.
- [ ] Database backup created.
- [ ] Queue volume backup plan verified.
- [ ] `.env` contains real production values and is not committed.
- [ ] Authentication mode confirmed with Edmingle.
- [ ] `/app/data` is persistent and writable by the container user.
- [ ] `/app/logs` is persistent and writable by the container user.
- [ ] `webhook` and `replay` services are running.
- [ ] `/ready` is healthy.
- [ ] Queue depth is monitored.
- [ ] Reverse proxy route is confirmed.
- [ ] Rollback path is known before traffic cutover.
