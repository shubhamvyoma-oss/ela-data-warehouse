CREATE SCHEMA IF NOT EXISTS system;
CREATE SCHEMA IF NOT EXISTS bronze;
CREATE SCHEMA IF NOT EXISTS silver;
CREATE SCHEMA IF NOT EXISTS gold;

CREATE TABLE IF NOT EXISTS system.schema_migrations (
    version text PRIMARY KEY,
    checksum_sha256 text NOT NULL,
    applied_at timestamp with time zone NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS system.pipeline_runs (
    run_id uuid PRIMARY KEY,
    pipeline_name text NOT NULL,
    run_type text NOT NULL,
    status text NOT NULL CHECK (
        status IN ('scheduled', 'running', 'succeeded', 'failed', 'cancelled')
    ),
    scheduled_for timestamp with time zone,
    started_at timestamp with time zone NOT NULL DEFAULT now(),
    finished_at timestamp with time zone,
    rows_read bigint NOT NULL DEFAULT 0 CHECK (rows_read >= 0),
    rows_written bigint NOT NULL DEFAULT 0 CHECK (rows_written >= 0),
    rows_rejected bigint NOT NULL DEFAULT 0 CHECK (rows_rejected >= 0),
    checkpoint_before jsonb,
    checkpoint_after jsonb,
    error_category text,
    error_message text,
    host_name text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    CHECK (
        (status IN ('scheduled', 'running') AND finished_at IS NULL)
        OR (status IN ('succeeded', 'failed', 'cancelled') AND finished_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_name_started
    ON system.pipeline_runs (pipeline_name, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status
    ON system.pipeline_runs (status, started_at DESC);

CREATE TABLE IF NOT EXISTS system.audit_events (
    audit_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id uuid REFERENCES system.pipeline_runs(run_id) ON DELETE SET NULL,
    component text NOT NULL,
    event_type text NOT NULL,
    status text NOT NULL CHECK (status IN ('info', 'succeeded', 'warning', 'failed')),
    occurred_at timestamp with time zone NOT NULL DEFAULT now(),
    row_count bigint CHECK (row_count IS NULL OR row_count >= 0),
    duration_ms bigint CHECK (duration_ms IS NULL OR duration_ms >= 0),
    details jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_audit_events_run
    ON system.audit_events (run_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_audit_events_component
    ON system.audit_events (component, occurred_at DESC);

CREATE TABLE IF NOT EXISTS system.collector_checkpoints (
    collector_name text NOT NULL,
    partition_key text NOT NULL DEFAULT 'default',
    checkpoint jsonb NOT NULL,
    updated_at timestamp with time zone NOT NULL DEFAULT now(),
    last_committed_run_id uuid REFERENCES system.pipeline_runs(run_id) ON DELETE SET NULL,
    PRIMARY KEY (collector_name, partition_key)
);

CREATE TABLE IF NOT EXISTS system.scheduler_jobs (
    job_name text PRIMARY KEY,
    collector_name text NOT NULL,
    enabled boolean NOT NULL DEFAULT false,
    interval_minutes integer NOT NULL CHECK (interval_minutes > 0),
    next_run_at timestamp with time zone,
    last_run_id uuid REFERENCES system.pipeline_runs(run_id) ON DELETE SET NULL,
    last_started_at timestamp with time zone,
    last_finished_at timestamp with time zone,
    updated_at timestamp with time zone NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS system.credential_metadata (
    credential_name text PRIMARY KEY,
    provider text NOT NULL,
    valid_from timestamp with time zone,
    expires_at timestamp with time zone,
    last_rotated_at timestamp with time zone,
    status text NOT NULL DEFAULT 'unknown',
    updated_at timestamp with time zone NOT NULL DEFAULT now(),
    CHECK (credential_name !~* '(password|secret|token|key_value)')
);

COMMENT ON TABLE system.credential_metadata IS
    'Non-secret credential lifecycle metadata only. Credential values are forbidden.';

CREATE TABLE IF NOT EXISTS system.manual_import_files (
    import_id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES system.pipeline_runs(run_id),
    source_name text NOT NULL,
    original_filename text NOT NULL,
    file_sha256 text NOT NULL CHECK (length(file_sha256) = 64),
    file_size_bytes bigint NOT NULL CHECK (file_size_bytes >= 0),
    status text NOT NULL CHECK (status IN ('validating', 'loaded', 'rejected', 'failed')),
    rows_read bigint NOT NULL DEFAULT 0 CHECK (rows_read >= 0),
    rows_loaded bigint NOT NULL DEFAULT 0 CHECK (rows_loaded >= 0),
    rows_rejected bigint NOT NULL DEFAULT 0 CHECK (rows_rejected >= 0),
    imported_at timestamp with time zone NOT NULL DEFAULT now(),
    UNIQUE (source_name, file_sha256)
);
