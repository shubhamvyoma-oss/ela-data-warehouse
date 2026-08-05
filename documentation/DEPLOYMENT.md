# Deployment

## Safety boundary

The warehouse deploys independently from the production `edmingle-webhook` container. It exposes no host port, uses separate Docker names and volumes, and must connect to a database other than `webhook_db`.

The audited VPS currently has insufficient free disk for the historical attendance load. Production deployment and ingestion remain blocked until storage is expanded and backup/restore verification passes.

## Required approvals and prerequisites

- repository is private and the deployment commit is approved
- at least 20 GB free after Docker image installation for the foundation; historical loads require a separately sized data volume
- root-owned Docker inventory and disk usage are understood
- warehouse database and least-privilege roles exist
- PostgreSQL firewall and `pg_hba.conf` rules are approved
- database backup and restore have been tested
- `.env` exists only on the server with mode `0600`
- API credentials have been validated without writing them to logs
- scheduler and every job remain disabled during initial deployment

## Staged deployment

1. Clone the approved commit into a new warehouse directory.
2. Create `.env` from `.env.example` and enter server-side secrets.
3. Build without starting services:

   ```bash
   docker compose build
   ```

4. Run database migrations:

   ```bash
   docker compose --profile tools run --rm warehouse-migrate
   ```

5. Run preflight:

   ```bash
   docker compose --profile tools run --rm warehouse-cli
   ```

6. Run one collector manually with a controlled time window.

   ```bash
   docker compose --profile tools run --rm warehouse-cli \
     python warehouse_cli.py collect attendance
   ```
7. Reconcile source counts, Bronze counts, checkpoints, and audit rows.
8. Start the scheduler with global and job-level schedules still disabled:

   ```bash
   docker compose up -d warehouse-scheduler
   ```

9. Enable one job at a time after operational approval.

No step routes webhook traffic or changes Caddy.

## Rollback

Stop only warehouse resources:

```bash
docker compose stop warehouse-scheduler
```

Preserve the database, `ela_warehouse_data`, and logs for diagnosis. Do not remove volumes and do not reverse schema migrations by dropping data. Restore the last approved image and configuration, run preflight, and restart the scheduler.
