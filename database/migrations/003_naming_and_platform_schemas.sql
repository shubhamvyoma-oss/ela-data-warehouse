CREATE SCHEMA IF NOT EXISTS audit;
CREATE SCHEMA IF NOT EXISTS monitoring;

-- Move historical operational records out of the current-state system schema.
ALTER TABLE system.pipeline_runs SET SCHEMA audit;
ALTER TABLE audit.pipeline_runs RENAME COLUMN run_id TO id;

ALTER TABLE system.audit_events RENAME TO events;
ALTER TABLE system.events SET SCHEMA audit;
ALTER TABLE audit.events RENAME COLUMN audit_id TO id;

ALTER TABLE system.manual_import_files RENAME TO manual_imports;
ALTER TABLE system.manual_imports SET SCHEMA audit;
ALTER TABLE audit.manual_imports RENAME COLUMN import_id TO id;

-- Apply the frozen snake_case, purpose-oriented system table names.
ALTER TABLE system.collector_checkpoints RENAME TO collection_checkpoints;
ALTER TABLE system.credential_metadata RENAME TO api_credentials;
ALTER TABLE system.scheduler_jobs RENAME COLUMN enabled TO is_enabled;

-- Every mutable platform table receives a conventional id primary key while
-- retaining its business key as a unique constraint for idempotent upserts.
ALTER TABLE system.collection_checkpoints
    ADD COLUMN id bigint GENERATED ALWAYS AS IDENTITY;
ALTER TABLE system.collection_checkpoints
    DROP CONSTRAINT collector_checkpoints_pkey;
ALTER TABLE system.collection_checkpoints
    ADD CONSTRAINT collection_checkpoints_pkey PRIMARY KEY (id);
ALTER TABLE system.collection_checkpoints
    ADD CONSTRAINT collection_checkpoints_business_key
    UNIQUE (collector_name, partition_key);

ALTER TABLE system.scheduler_jobs
    ADD COLUMN id bigint GENERATED ALWAYS AS IDENTITY;
ALTER TABLE system.scheduler_jobs
    DROP CONSTRAINT scheduler_jobs_pkey;
ALTER TABLE system.scheduler_jobs
    ADD CONSTRAINT scheduler_jobs_pkey PRIMARY KEY (id);
ALTER TABLE system.scheduler_jobs
    ADD CONSTRAINT scheduler_jobs_job_name_key UNIQUE (job_name);

ALTER TABLE system.api_credentials
    ADD COLUMN id bigint GENERATED ALWAYS AS IDENTITY;
ALTER TABLE system.api_credentials
    DROP CONSTRAINT credential_metadata_pkey;
ALTER TABLE system.api_credentials
    ADD CONSTRAINT api_credentials_pkey PRIMARY KEY (id);
ALTER TABLE system.api_credentials
    ADD CONSTRAINT api_credentials_credential_name_key UNIQUE (credential_name);

-- Bronze uses the same id/raw_payload/received_at/created_at vocabulary.
ALTER TABLE bronze.edmingle_api_records RENAME COLUMN bronze_record_id TO id;
ALTER TABLE bronze.edmingle_api_records RENAME COLUMN collected_at TO received_at;
ALTER TABLE bronze.edmingle_api_records RENAME COLUMN inserted_at TO created_at;

ALTER TABLE bronze.manual_import_rows RENAME COLUMN bronze_row_id TO id;
ALTER TABLE bronze.manual_import_rows RENAME COLUMN raw_row TO raw_payload;
ALTER TABLE bronze.manual_import_rows RENAME COLUMN inserted_at TO created_at;

ALTER TABLE bronze.rejected_records RENAME COLUMN rejection_id TO id;

-- Status values are a controlled uppercase vocabulary.
ALTER TABLE audit.pipeline_runs DROP CONSTRAINT pipeline_runs_status_check;
ALTER TABLE audit.pipeline_runs DROP CONSTRAINT pipeline_runs_check;
UPDATE audit.pipeline_runs
SET status = CASE status
    WHEN 'scheduled' THEN 'SCHEDULED'
    WHEN 'running' THEN 'RUNNING'
    WHEN 'succeeded' THEN 'SUCCESS'
    WHEN 'failed' THEN 'FAILED'
    WHEN 'cancelled' THEN 'CANCELLED'
    ELSE upper(status)
END;
ALTER TABLE audit.pipeline_runs
    ADD CONSTRAINT pipeline_runs_status_check
    CHECK (status IN ('SCHEDULED', 'RUNNING', 'SUCCESS', 'FAILED', 'CANCELLED'));
ALTER TABLE audit.pipeline_runs
    ADD CONSTRAINT pipeline_runs_lifecycle_check
    CHECK (
        (status IN ('SCHEDULED', 'RUNNING') AND finished_at IS NULL)
        OR (status IN ('SUCCESS', 'FAILED', 'CANCELLED') AND finished_at IS NOT NULL)
    );

ALTER TABLE audit.events DROP CONSTRAINT audit_events_status_check;
UPDATE audit.events
SET status = CASE status
    WHEN 'info' THEN 'INFO'
    WHEN 'succeeded' THEN 'SUCCESS'
    WHEN 'warning' THEN 'WARNING'
    WHEN 'failed' THEN 'FAILED'
    ELSE upper(status)
END;
ALTER TABLE audit.events
    ADD CONSTRAINT events_status_check
    CHECK (status IN ('INFO', 'SUCCESS', 'WARNING', 'FAILED'));

ALTER TABLE audit.manual_imports DROP CONSTRAINT manual_import_files_status_check;
UPDATE audit.manual_imports SET status = upper(status);
ALTER TABLE audit.manual_imports
    ADD CONSTRAINT manual_imports_status_check
    CHECK (status IN ('VALIDATING', 'LOADED', 'REJECTED', 'FAILED'));

UPDATE system.api_credentials SET status = upper(status);

-- PostgreSQL is the source of truth for registered platform components.
CREATE TABLE IF NOT EXISTS system.configuration (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    configuration_key text NOT NULL UNIQUE,
    configuration_value jsonb NOT NULL,
    description text,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    updated_at timestamp with time zone NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS system.collectors (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    collector_name text NOT NULL UNIQUE,
    description text NOT NULL,
    owner_name text,
    collector_version text NOT NULL DEFAULT '1',
    is_enabled boolean NOT NULL DEFAULT false,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    updated_at timestamp with time zone NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS system.source_systems (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_system_name text NOT NULL UNIQUE,
    description text NOT NULL,
    is_enabled boolean NOT NULL DEFAULT false,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    updated_at timestamp with time zone NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS system.pipelines (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pipeline_name text NOT NULL UNIQUE,
    description text NOT NULL,
    owner_name text,
    pipeline_version text NOT NULL DEFAULT '1',
    is_enabled boolean NOT NULL DEFAULT false,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    updated_at timestamp with time zone NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS system.feature_flags (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    feature_name text NOT NULL UNIQUE,
    description text NOT NULL,
    is_enabled boolean NOT NULL DEFAULT false,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    updated_at timestamp with time zone NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS system.platform_metadata (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    metadata_key text NOT NULL UNIQUE,
    metadata_value jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    updated_at timestamp with time zone NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS system.execution_locks (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lock_name text NOT NULL UNIQUE,
    owner_name text NOT NULL,
    acquired_at timestamp with time zone NOT NULL DEFAULT now(),
    expires_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    updated_at timestamp with time zone NOT NULL DEFAULT now(),
    CHECK (expires_at > acquired_at)
);

INSERT INTO system.collectors (collector_name, description)
VALUES
    ('attendance', 'Edmingle attendance report collector'),
    ('enrollment', 'Edmingle batch enrollment collector'),
    ('batches', 'Edmingle master batch collector'),
    ('catalogue', 'Edmingle course catalogue collector')
ON CONFLICT (collector_name) DO NOTHING;

INSERT INTO system.source_systems (source_system_name, description)
VALUES
    ('edmingle', 'Edmingle learning management system'),
    ('manual_files', 'Approved CSV, TSV, and Excel imports')
ON CONFLICT (source_system_name) DO NOTHING;

CREATE TABLE IF NOT EXISTS monitoring.service_health (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    component_name text NOT NULL UNIQUE,
    status text NOT NULL CHECK (status IN ('HEALTHY', 'DEGRADED', 'UNHEALTHY', 'UNKNOWN')),
    heartbeat_at timestamp with time zone,
    last_checked_at timestamp with time zone NOT NULL DEFAULT now(),
    has_error boolean NOT NULL DEFAULT false,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    updated_at timestamp with time zone NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS monitoring.collector_status (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    collector_name text NOT NULL UNIQUE,
    status text NOT NULL CHECK (status IN ('IDLE', 'RUNNING', 'SUCCESS', 'FAILED', 'DISABLED')),
    last_run_at timestamp with time zone,
    last_success_at timestamp with time zone,
    has_error boolean NOT NULL DEFAULT false,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    updated_at timestamp with time zone NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS monitoring.database_health (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    database_name text NOT NULL UNIQUE,
    status text NOT NULL CHECK (status IN ('HEALTHY', 'DEGRADED', 'UNHEALTHY', 'UNKNOWN')),
    last_checked_at timestamp with time zone NOT NULL DEFAULT now(),
    has_error boolean NOT NULL DEFAULT false,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    updated_at timestamp with time zone NOT NULL DEFAULT now()
);

COMMENT ON TABLE system.api_credentials IS
    'Non-secret credential lifecycle metadata only. Credential values are forbidden.';
COMMENT ON SCHEMA audit IS
    'Append-only operational history. Business data is forbidden.';
COMMENT ON SCHEMA monitoring IS
    'Current platform health and operational state.';
