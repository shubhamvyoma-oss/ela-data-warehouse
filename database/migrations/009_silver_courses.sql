-- Migration 009: silver.courses -- the first reconciled Silver model
-- Forward-only. Do not edit 001-008.
--
-- Source: bronze.course_batch_merge only (NOT bronze.course_catalog or
-- bronze.course_catalogue_raw). Project-owner decision on the 3-way
-- catalogue-domain overlap flagged in ROADMAP.md:
--   1. Archived batches are EXCLUDED from silver.courses (Active/Completed
--      only) -- filtered here in Silver via batch_status, even though the
--      Bronze source table (course_batch_merge) itself keeps Archived rows
--      for its own Is_Latest_Batch history computation.
--   2. Junk/test-batch filtering trusts course_batch_merge's keyword rule
--      (batch_name containing "test batch"; bundle_name containing
--      test/demo/dummy/sample when there's no catalogue match) -- already
--      applied at collection time in that table. course_catalog's fixed
--      20-batch-id exclusion list is NOT re-applied here.
--   3. bronze.course_catalogue_raw remains unreconciled (per its own
--      README) -- it has no batch merge at all, so it isn't a candidate
--      source for this per-batch grain.
-- See ROADMAP.md for the full reconciliation record.

BEGIN;

-- ---------------------------------------------------------------------
-- silver.courses  <- bronze.course_batch_merge (Active/Completed only)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.courses (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    -- batch_id when the row has a batch; for catalogue-only rows
    -- (has_batch = false, batch_id NULL) a synthetic 'catalogue-only:<bundle_id>'
    -- key instead -- Postgres never treats two NULLs as equal for UNIQUE
    -- purposes, so keying on batch_id alone would silently duplicate every
    -- catalogue-only bundle on each re-run (the exact gap flagged in
    -- bronze.course_batch_merge's own README). course_key fixes that.
    course_key text NOT NULL,
    bundle_id text,
    bundle_name text,
    batch_id text,
    batch_name text,
    batch_status text,
    has_batch boolean,
    is_latest_batch boolean,
    start_date date,
    end_date date,
    tutor_name text,
    tutor_id text,
    tutors text,
    tutor_ids text,
    batch_enrollment_count integer,
    bundle_enrollment_count integer,
    course_name text,
    course_ids text,
    subject text,
    level text,
    language text,
    examination text,
    course_type text,
    course_division text,
    certificate text,
    course_sponsor text,
    course_title_sanskrit text,
    number_of_lectures text,
    duration text,
    personas text,
    computer_based_assessment text,
    product_id text,
    sss_category text,
    viniyoga text,
    adhyayanam_category text,
    term_of_course text,
    position_in_funnel text,
    division text,
    is_catalogue_match boolean,
    catalogue_status text,
    final_status text,
    source_updated_at timestamp with time zone,
    silver_updated_at timestamp with time zone NOT NULL DEFAULT now(),
    UNIQUE (course_key)
);
COMMENT ON TABLE silver.courses IS 'Reconciled catalogue/batch model. Source: bronze.course_batch_merge only, filtered to Active/Completed batches (Archived excluded) plus catalogue-only rows. bronze.course_catalog and bronze.course_catalogue_raw are not inputs -- see this migration''s header and ROADMAP.md for the reconciliation decision.';

INSERT INTO system.pipelines (pipeline_name, description, is_enabled)
VALUES
    ('silver_courses', 'silver_courses -> silver.courses (reconciled from bronze.course_batch_merge, Active/Completed only)', false)
ON CONFLICT (pipeline_name) DO UPDATE SET
    description = EXCLUDED.description;

COMMIT;
