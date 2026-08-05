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
