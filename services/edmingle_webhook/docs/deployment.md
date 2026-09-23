# Deployment

This guide describes the production deployment process for the Docker-based webhook
implementation. **Updated 2026-09-23** to match the actual VPS deployment (this was
originally written as a plan before the real cutover happened): the live deployment uses
`docker/compose/vps-webhook.yml` as an override on top of this folder's own
`docker-compose.yml` -- it renames the container/image/volumes/network so this stack
doesn't collide with the older standalone `edmingle-webhook` deployment, remaps the
published port to `127.0.0.1:5101` (a host-level reverse proxy -- Caddy on this VPS --
handles the public `:443` -> `:5101` hop; the service itself is never exposed on `0.0.0.0`
directly), and adds log rotation. Every `docker compose` command below needs both `-f`
flags when run against the real VPS deployment:

```bash
docker compose -f docker-compose.yml -f ../../docker/compose/vps-webhook.yml <command>
```

(paths above are relative to this `services/edmingle_webhook/` directory; adjust if running
from the repo root).

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

In this repo's own `docker-compose.yml`, the data volume is named
`edmingle_webhook_data`. On the actual VPS deployment, `docker/compose/vps-webhook.yml`
renames it to `ela_dw_webhook_data` (and the logs volume to `ela_dw_webhook_logs`) -- use
the real name for any `docker run -v <name>:/data ...` backup/inspection command against
the live deployment.

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
docker compose -f docker-compose.yml -f ../../docker/compose/vps-webhook.yml build webhook replay
docker compose -f docker-compose.yml -f ../../docker/compose/vps-webhook.yml up -d webhook replay
```

The Docker image installs dependencies directly from `requirements.txt`. It does not create or use a virtual environment inside the container.

**Before this fix (2026-09-23), the `replay` service had never actually run on the VPS --
only `webhook` was deployed.** Deploying it for the first time immediately hit a real bug:
`python scripts/replay_worker.py` crash-looped with `ModuleNotFoundError: No module named
'app'`, because a bare `python script.py` invocation only puts the script's own directory
(`scripts/`) on `sys.path`, not the working directory -- unlike `gunicorn ... wsgi:app`
(used by `webhook`), which adds the working directory itself. Fixed by adding
`ENV PYTHONPATH=/app` to the Dockerfile. If you ever see this exact traceback again after
changing the Dockerfile or base image, check that env var is still set.

The `replay` service also has its own healthcheck (`scripts/replay_healthcheck.py`,
checking a heartbeat file `replay_worker.py` touches after every loop iteration) instead of
inheriting the image's default HTTP-based one -- `replay` doesn't serve HTTP, so the
inherited check would always fail (connection refused on port 5100) and report the
container unhealthy forever even while it's working correctly.

## Health Verification

Check container status:

```bash
docker compose -f docker-compose.yml -f ../../docker/compose/vps-webhook.yml ps
```

Check endpoints (`5100` here is the container's own internal port; on the VPS itself this
is reachable at `127.0.0.1:5101` per the port remap above, or publicly via
`https://ela-webhooks.vyoma.org` through Caddy):

```bash
curl -fsS http://127.0.0.1:5100/live
curl -fsS http://127.0.0.1:5100/health
curl -fsS http://127.0.0.1:5100/ready
curl -fsS http://127.0.0.1:5100/metrics
curl -fsS -X OPTIONS http://127.0.0.1:5100/edmingle/webhook
curl -fsS http://127.0.0.1:5100/edmingle/webhook/
```

Expected:

- `/live` returns `200`.
- `/health` returns `{"status":"running"}` with HTTP 200 for production compatibility.
- `/ready` returns `200` only when PostgreSQL is reachable.
- `/metrics` returns Prometheus text format.
- Webhook validation returns `200 {"status":"ok"}` for GET and OPTIONS,
  including the trailing-slash form.

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
