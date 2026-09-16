-- Migration 007: Silver-layer tables (typed/normalized, single-source only)
-- Forward-only. Do not edit 001-006.
--
-- These are the first real Silver models: a typed, normalized pass over
-- Bronze tables that don't require reconciling multiple competing sources.
-- Catalogue/attendance/enrollment Silver entities that DO have competing
-- Bronze sources are deliberately deferred pending a business decision on
-- which source is authoritative (see ROADMAP.md).

BEGIN;

-- ---------------------------------------------------------------------
-- silver.students  <- bronze.students
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.students (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id text NOT NULL,
    name text,
    email text,
    primary_contact_number text,
    secondary_contact_number text,
    parent_name text,
    parent_email text,
    parent_contact_number text,
    registration_number text,
    role text,
    status text,
    is_archived boolean,
    registration_date date,
    age integer,
    last_name text,
    username text,
    source_updated_at timestamp with time zone,
    silver_updated_at timestamp with time zone NOT NULL DEFAULT now(),
    UNIQUE (user_id)
);
COMMENT ON TABLE silver.students IS 'Typed/normalized pass over bronze.students. Single source, no reconciliation needed.';

-- ---------------------------------------------------------------------
-- silver.class_id_lookup  <- bronze.class_id_lookup
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.class_id_lookup (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    batch_id text NOT NULL,
    class_id text NOT NULL,
    bundle_id text,
    bundle_name text,
    batch_name text,
    tutor_id text,
    tutor_name text,
    total_classes integer,
    completed_classes integer,
    cancelled_classes integer,
    num_users integer,
    associated_masterbatches text,
    source_updated_at timestamp with time zone,
    silver_updated_at timestamp with time zone NOT NULL DEFAULT now(),
    UNIQUE (batch_id, class_id)
);
COMMENT ON TABLE silver.class_id_lookup IS 'Typed pass over bronze.class_id_lookup, excluding rows with no resolved class_id (a batch with zero classes is meaningful in Bronze for completeness, not useful in Silver).';

-- ---------------------------------------------------------------------
-- silver.enrollment_reports  <- bronze.enrollment_reports
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.enrollment_reports (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    enrollment_id text NOT NULL,
    enrollment_day date,
    user_id text,
    name text,
    email text,
    contact_number text,
    state text,
    registration_number text,
    learner_type text,
    enrollment_mode text,
    enrollment_status text,
    bundle_id text,
    bundle_name text,
    batch_ids text,
    product_type text,
    product_type_label text,
    platform_type text,
    enrollment_expiration_date date,
    preferred_categories text,
    source_updated_at timestamp with time zone,
    silver_updated_at timestamp with time zone NOT NULL DEFAULT now(),
    UNIQUE (enrollment_id)
);
COMMENT ON TABLE silver.enrollment_reports IS 'Typed/normalized pass over bronze.enrollment_reports. Distinct from any future silver.course_enrollments (deferred -- see ROADMAP.md).';

-- ---------------------------------------------------------------------
-- Registry: register the 3 transforms as pipelines (disabled, same pattern
-- as api_scripts jobs)
-- ---------------------------------------------------------------------
INSERT INTO system.pipelines (pipeline_name, description, is_enabled)
VALUES
    ('silver_students', 'silver_students -> silver.students (typed/normalized pass over bronze.students)', false),
    ('silver_class_id_lookup', 'silver_class_id_lookup -> silver.class_id_lookup (typed pass over bronze.class_id_lookup, drops unresolved class_id rows)', false),
    ('silver_enrollment_reports', 'silver_enrollment_reports -> silver.enrollment_reports (typed/normalized pass over bronze.enrollment_reports)', false)
ON CONFLICT (pipeline_name) DO UPDATE SET
    description = EXCLUDED.description;

COMMIT;
