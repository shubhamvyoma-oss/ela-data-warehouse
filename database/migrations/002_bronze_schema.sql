CREATE TABLE IF NOT EXISTS bronze.edmingle_api_records (
    bronze_record_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    resource text NOT NULL,
    record_key text NOT NULL,
    source_updated_at timestamp with time zone,
    collected_at timestamp with time zone NOT NULL,
    pipeline_run_id uuid NOT NULL REFERENCES system.pipeline_runs(run_id),
    payload_sha256 text NOT NULL CHECK (length(payload_sha256) = 64),
    request_context jsonb NOT NULL DEFAULT '{}'::jsonb,
    raw_payload jsonb NOT NULL,
    inserted_at timestamp with time zone NOT NULL DEFAULT now(),
    UNIQUE (resource, record_key, payload_sha256)
);

CREATE INDEX IF NOT EXISTS idx_edmingle_api_records_resource_collected
    ON bronze.edmingle_api_records (resource, collected_at DESC);
CREATE INDEX IF NOT EXISTS idx_edmingle_api_records_run
    ON bronze.edmingle_api_records (pipeline_run_id);
CREATE INDEX IF NOT EXISTS idx_edmingle_api_records_source_updated
    ON bronze.edmingle_api_records (resource, source_updated_at)
    WHERE source_updated_at IS NOT NULL;

CREATE TABLE IF NOT EXISTS bronze.manual_import_rows (
    bronze_row_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    import_id uuid NOT NULL REFERENCES system.manual_import_files(import_id),
    pipeline_run_id uuid NOT NULL REFERENCES system.pipeline_runs(run_id),
    source_name text NOT NULL,
    source_row_number bigint NOT NULL CHECK (source_row_number > 0),
    row_sha256 text NOT NULL CHECK (length(row_sha256) = 64),
    raw_row jsonb NOT NULL,
    inserted_at timestamp with time zone NOT NULL DEFAULT now(),
    UNIQUE (import_id, source_row_number),
    UNIQUE (source_name, row_sha256, import_id)
);

CREATE INDEX IF NOT EXISTS idx_manual_import_rows_source
    ON bronze.manual_import_rows (source_name, inserted_at DESC);
CREATE INDEX IF NOT EXISTS idx_manual_import_rows_run
    ON bronze.manual_import_rows (pipeline_run_id);

CREATE TABLE IF NOT EXISTS bronze.rejected_records (
    rejection_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pipeline_run_id uuid NOT NULL REFERENCES system.pipeline_runs(run_id),
    source_name text NOT NULL,
    source_reference text,
    reason_code text NOT NULL,
    reason_message text NOT NULL,
    rejected_at timestamp with time zone NOT NULL DEFAULT now(),
    payload_sha256 text,
    raw_payload jsonb
);

COMMENT ON TABLE bronze.rejected_records IS
    'Quarantined source records. Access must be restricted because payloads may contain PII.';
