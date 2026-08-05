SELECT current_database() AS database_name,
       current_user AS database_user,
       current_setting('server_version') AS postgres_version;

SELECT schema_name
FROM information_schema.schemata
WHERE schema_name IN ('system', 'audit', 'monitoring', 'bronze', 'silver', 'gold')
ORDER BY schema_name;

SELECT version, checksum_sha256, applied_at
FROM system.schema_migrations
ORDER BY version;

SELECT status, count(*)
FROM audit.pipeline_runs
GROUP BY status
ORDER BY status;
