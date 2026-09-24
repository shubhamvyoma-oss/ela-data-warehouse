-- Removes the word "collector" from every database object name in the
-- warehouse. All affected tables are empty (system.collection_checkpoints
-- and system.api_scripts hold live registry rows but no historical data
-- keyed differently under the old name; monitoring.collector_status and
-- system.scheduler_jobs are both 0 rows), so these are pure renames with
-- nothing to migrate.

ALTER TABLE system.collection_checkpoints RENAME COLUMN collector_name TO job_name;
ALTER TABLE system.collection_checkpoints
    RENAME CONSTRAINT collector_checkpoints_last_committed_run_id_fkey
    TO collection_checkpoints_last_committed_run_id_fkey;

ALTER TABLE system.api_scripts RENAME COLUMN collector_name TO job_name;
ALTER TABLE system.api_scripts RENAME COLUMN collector_version TO job_version;
ALTER TABLE system.api_scripts
    RENAME CONSTRAINT api_scripts_collector_name_key TO api_scripts_job_name_key;

-- system.scheduler_jobs already has its own job_name column (the scheduled
-- entry's own label, e.g. "attendance_daily"); collector_name identifies
-- which registered job it runs, so it is renamed to job_key to avoid a
-- naming collision between the two distinct concepts.
ALTER TABLE system.scheduler_jobs RENAME COLUMN collector_name TO job_key;

ALTER TABLE monitoring.collector_status RENAME TO job_status;
ALTER TABLE monitoring.job_status RENAME COLUMN collector_name TO job_name;
ALTER TABLE monitoring.job_status RENAME CONSTRAINT collector_status_pkey TO job_status_pkey;
ALTER TABLE monitoring.job_status
    RENAME CONSTRAINT collector_status_collector_name_key TO job_status_job_name_key;
ALTER TABLE monitoring.job_status
    RENAME CONSTRAINT collector_status_status_check TO job_status_status_check;
