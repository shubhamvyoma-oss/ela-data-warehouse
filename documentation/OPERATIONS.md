# Operations

## Daily checks

- scheduler container health
- failed `audit.pipeline_runs`
- overdue scheduler jobs
- API-key expiry metadata
- collector checkpoint age
- Bronze row growth by resource
- rejected-record growth
- database and filesystem free space
- PostgreSQL backup age and restore-test status

## Useful queries

```sql
SELECT pipeline_name, status, started_at, finished_at,
       rows_read, rows_written, rows_rejected, error_category
FROM audit.pipeline_runs
ORDER BY started_at DESC
LIMIT 50;
```

```sql
SELECT collector_name, partition_key, updated_at, checkpoint
FROM system.collection_checkpoints
ORDER BY updated_at;
```

```sql
SELECT resource, count(*) AS bronze_versions, max(received_at) AS latest_collection
FROM bronze.edmingle_api_records
GROUP BY resource
ORDER BY resource;
```

Audit and logs intentionally exclude raw payloads. Access to Bronze and rejected records should be restricted because they may contain personal data.

## Scheduled jobs actually running on the VPS

**Not** managed by services/scheduler (still fully inert, see ROADMAP.md) --
these are plain crontab entries on the projectdev user, since sudo/systemd
access isn't available and this is a single job, not a case for standing
up new infrastructure. `crontab -l` on the VPS is the source of truth;
this section exists so the job isn't forgotten (it lives outside git).

| Job | Schedule | Command |
| --- | --- | --- |
| `silver_enrollments` refresh | every minute | `cd /home/projectdev/ela-data-warehouse && docker compose run --rm -T warehouse-cli python warehouse_cli.py transform enrollments` |

Logs to `logs/enrollments_transform_cron.log` in the repo root (gitignored,
VPS-local). Re-running this transform is always safe -- it's a full
idempotent re-scan of bronze.enrollment_reports (static, ~8.5k rows) and
bronze.webhook_events (growing; filtered to transaction.user_purchase_completed,
indexed -- see migration 013_webhook_events_transaction_index.sql), upserted
into silver.enrollments keyed on enrollment_id.
