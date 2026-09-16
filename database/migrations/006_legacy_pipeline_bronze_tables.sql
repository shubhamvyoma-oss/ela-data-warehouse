-- Migration 006: Bronze tables for ported legacy pipelines
-- Forward-only. Do not edit 001-005. See documentation/decisions/ADR-001.
--
-- Each table holds the ALREADY-TRANSFORMED output of a ported legacy script
-- (course_catalog.py, resolve_class_ids.py, etc.) rather than a raw payload.
-- This is a deliberate, explicit deviation from the "Bronze = raw only" rule
-- for this specific body of work (see plan doc), approved by the project owner.

BEGIN;

-- ---------------------------------------------------------------------
-- bronze.course_catalog  <- Attendance data/build_course_catalog.py
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bronze.course_catalog (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pipeline_run_id uuid NOT NULL REFERENCES audit.pipeline_runs(id),
    bundle_id text,
    bundle_name text,
    batch_id text,
    batch_name text,
    batch_status text,
    start_date date,
    end_date date,
    tutor_name text,
    tutor_id text,
    batch_enrollment_count numeric,
    course_name text,
    tutors text,
    tutor_ids text,
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
    catalogue_raw_status text,
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
    bundle_enrollment_count numeric,
    is_latest_batch boolean,
    has_batch boolean,
    catalogue_status text,
    final_status text,
    received_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    UNIQUE (batch_id, bundle_id)
);
COMMENT ON TABLE bronze.course_catalog IS 'Ported from Attendance data/build_course_catalog.py. Transformed output (Is_Latest_Batch/Final_Status/enrollment rollups already computed) stored directly, per explicit project-owner decision.';

-- ---------------------------------------------------------------------
-- bronze.course_batch_merge  <- corses-batches/Course_Batch_Merge (5).py
-- Replaces the retired 'batches' collector (see system.api_scripts update below)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bronze.course_batch_merge (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pipeline_run_id uuid NOT NULL REFERENCES audit.pipeline_runs(id),
    bundle_id text,
    bundle_name text,
    batch_id text,
    batch_name text,
    batch_status text,
    start_date date,
    end_date date,
    tutor_name text,
    tutor_id text,
    batch_enrollment_count numeric,
    course_name text,
    tutors text,
    tutor_ids text,
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
    catalogue_raw_status text,
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
    bundle_enrollment_count numeric,
    is_latest_batch boolean,
    has_batch boolean,
    catalogue_status text,
    final_status text,
    received_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    UNIQUE (batch_id, bundle_id)
);
COMMENT ON TABLE bronze.course_batch_merge IS 'Ported from corses-batches/Course_Batch_Merge (5).py. Includes Archived batches (unlike course_catalog); kept as a separate, unreconciled table per explicit decision.';

-- ---------------------------------------------------------------------
-- bronze.course_catalogue_raw  <- corses-batches/course_catalogue_data (1).py
-- Dynamic/unknown columns from a generic JSON-normalize flatten: keep raw
-- payload plus a few promoted identity columns.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bronze.course_catalogue_raw (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pipeline_run_id uuid NOT NULL REFERENCES audit.pipeline_runs(id),
    bundle_id text,
    row_sha256 text NOT NULL CHECK (length(row_sha256) = 64),
    raw_payload jsonb NOT NULL,
    received_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    UNIQUE (bundle_id, row_sha256)
);
COMMENT ON TABLE bronze.course_catalogue_raw IS 'Ported from corses-batches/course_catalogue_data (1).py. Output columns vary by API response shape, so raw_payload retains the full flattened row; bundle_id promoted for lookups.';

-- ---------------------------------------------------------------------
-- bronze.class_id_lookup  <- Attendance data/resolve_class_ids.py
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bronze.class_id_lookup (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pipeline_run_id uuid NOT NULL REFERENCES audit.pipeline_runs(id),
    bundle_id text,
    bundle_name text,
    batch_id text NOT NULL,
    batch_name text,
    class_id text,
    tutor_name text,
    tutor_id text,
    total_classes numeric,
    completed_classes numeric,
    cancelled_classes numeric,
    num_users numeric,
    associated_masterbatches text,
    received_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    UNIQUE (batch_id, class_id)
);
COMMENT ON TABLE bronze.class_id_lookup IS 'Ported from Attendance data/resolve_class_ids.py. A batch resolving to zero classes stores one row with class_id NULL so the batch is never silently dropped.';

-- ---------------------------------------------------------------------
-- bronze.class_session_attendance  <- Attendance data/build_session_attendance.py
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bronze.class_session_attendance (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pipeline_run_id uuid NOT NULL REFERENCES audit.pipeline_runs(id),
    session_id text NOT NULL,
    class_id text,
    class_name text,
    master_batch_id text,
    master_batch_name text,
    bundle_id text,
    bundle_name text,
    class_date date,
    total_enrolled_at_session numeric,
    present_count numeric,
    not_marked_count numeric,
    attendance_pct numeric,
    taken_by_name text,
    individual_batch_attendance text,
    session_start_ist timestamp without time zone,
    session_end_ist timestamp without time zone,
    session_duration_minutes numeric,
    is_session_conducted boolean,
    session_number integer,
    received_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    UNIQUE (session_id)
);
COMMENT ON TABLE bronze.class_session_attendance IS 'Ported from Attendance data/build_session_attendance.py + shared logic in attendance_crossvalidation.py. session_number is scoped per master_batch_id, matching source behavior.';

-- ---------------------------------------------------------------------
-- bronze.report55_batch_attendance_summary  <- attendance/attendance.py
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bronze.report55_batch_attendance_summary (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pipeline_run_id uuid NOT NULL REFERENCES audit.pipeline_runs(id),
    batch_id text NOT NULL,
    batch_name text,
    bundle_id text,
    bundle_name text,
    course_id text,
    course_name text,
    teacher_id text,
    teacher_name text,
    total_students_enrolled numeric,
    first_class_date date,
    last_class_date date,
    first_class_attendance numeric,
    last_class_attendance numeric,
    total_present_marks numeric,
    total_absent_marks numeric,
    attendance_percentage numeric,
    average_class_attendance numeric,
    highest_class_attendance numeric,
    lowest_class_attendance numeric,
    average_rating numeric,
    retention_percentage numeric,
    attendance_drop numeric,
    summary_window_start date NOT NULL,
    summary_window_end date NOT NULL,
    received_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    UNIQUE (batch_id, summary_window_start, summary_window_end)
);
COMMENT ON TABLE bronze.report55_batch_attendance_summary IS 'Ported from attendance/attendance.py (report_type=55 pipeline), per-batch summary. summary_window_* records the date range this summary run covered, since the source script is a full-window recompute, not incremental.';

-- ---------------------------------------------------------------------
-- bronze.report55_session_attendance  <- attendance/attendance.py
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bronze.report55_session_attendance (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pipeline_run_id uuid NOT NULL REFERENCES audit.pipeline_runs(id),
    batch_id text NOT NULL,
    batch_name text,
    course_id text,
    course_name text,
    session_number integer,
    session_id text NOT NULL,
    class_date date,
    is_session_conducted boolean,
    present_count numeric,
    absent_count numeric,
    late_count numeric,
    total_marked numeric,
    session_attendance_percentage numeric,
    received_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    UNIQUE (batch_id, session_id)
);
COMMENT ON TABLE bronze.report55_session_attendance IS 'Ported from attendance/attendance.py (report_type=55 pipeline), per-session detail. Distinct from bronze.class_session_attendance, which comes from the separate /organization/attendances-based pipeline.';

-- ---------------------------------------------------------------------
-- bronze.students  <- ela_mis_datasets/edmingle_student_course_sync.py (student half)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bronze.students (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pipeline_run_id uuid NOT NULL REFERENCES audit.pipeline_runs(id),
    user_id text NOT NULL,
    name text,
    email text,
    contact_number text,
    contact_number_2 text,
    contact_number_2_country_id text,
    contact_number_2_dial_code text,
    contact_number_country_id text,
    contact_number_dial_code text,
    registration_date text,
    formatted_registration_date text,
    is_archived boolean,
    parent_contact_number text,
    parent_contact_number_country_id text,
    parent_contact_number_dial_code text,
    parent_email text,
    parent_name text,
    registration_number text,
    role text,
    status text,
    registration_time text,
    user_username text,
    custom_phone_number text,
    custom_age text,
    custom_last_name text,
    custom_user_name text,
    received_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    UNIQUE (user_id)
);
COMMENT ON TABLE bronze.students IS 'Ported from ela_mis_datasets/edmingle_student_course_sync.py (student roster half). Fills the previously-reserved api_scripts/students/ job.';

-- ---------------------------------------------------------------------
-- bronze.course_enrollments  <- ela_mis_datasets/edmingle_student_course_sync.py (course half)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bronze.course_enrollments (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pipeline_run_id uuid NOT NULL REFERENCES audit.pipeline_runs(id),
    user_id text NOT NULL,
    name text,
    email text,
    class_id text NOT NULL,
    class_name text,
    tutor_name text,
    total_classes numeric,
    present_count numeric,
    absent_count numeric,
    late_count numeric,
    excused_count numeric,
    start_date text,
    end_date text,
    master_batch_id text,
    master_batch_name text,
    classusers_start_date text,
    classusers_end_date text,
    batch_status text,
    cu_status text,
    cu_state text,
    institution_bundle_id text,
    archived_at text,
    bundle_id text,
    received_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    UNIQUE (user_id, class_id)
);
COMMENT ON TABLE bronze.course_enrollments IS 'Ported from ela_mis_datasets/edmingle_student_course_sync.py (course/enrollment half). Split from the same source script into its own job per one-responsibility convention.';

-- ---------------------------------------------------------------------
-- bronze.enrollment_reports  <- enrollments_reports/edmingle_export.py
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bronze.enrollment_reports (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pipeline_run_id uuid NOT NULL REFERENCES audit.pipeline_runs(id),
    enrollment_id text NOT NULL,
    enrollment_day text,
    user_id text,
    name text,
    email text,
    contact_number text,
    contact_number_country_id text,
    state text,
    registration_number text,
    learner_type text,
    enrollment_mode text,
    enrollment_status text,
    bundle_id text,
    bundle_name text,
    batch_ids text,
    batches text,
    product_type text,
    product_type_label text,
    platform_type text,
    enrollment_expiration_date text,
    shipping_details_json text,
    preferred_categories text,
    received_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    UNIQUE (enrollment_id)
);
COMMENT ON TABLE bronze.enrollment_reports IS 'Ported from enrollments_reports/edmingle_export.py (/reports/enrollment endpoint) — a distinct data source from bronze.course_enrollments.';

-- ---------------------------------------------------------------------
-- Registry updates: system.api_scripts / system.pipelines
-- ---------------------------------------------------------------------

-- Retire jobs not sourced from the six ported folders (history preserved, not deleted).
UPDATE system.api_scripts SET is_enabled = false, updated_at = now()
    WHERE collector_name IN ('batches', 'enrollment');
UPDATE system.pipelines SET is_enabled = false
    WHERE pipeline_name IN ('batches', 'enrollment');

-- Register new/replaced jobs. collector_version left at default '1'; all disabled
-- until deployment validation is approved, per AGENTS.md.
INSERT INTO system.api_scripts (collector_name, description, owner_name, is_enabled)
VALUES
    ('attendance', 'Report-type-55 attendance pipeline (batch + session summaries), ported from attendance/attendance.py', 'vyoma', false),
    ('catalogue', 'Course catalogue + masterbatch merge, ported from Attendance data/build_course_catalog.py', 'vyoma', false),
    ('class_id_lookup', 'Resolves class_id per batch, ported from Attendance data/resolve_class_ids.py', 'vyoma', false),
    ('class_session_attendance', 'Per-session attendance via /organization/attendances, ported from Attendance data/build_session_attendance.py', 'vyoma', false),
    ('course_batch_merge', 'Catalogue + all-status batch merge (incl. Archived), ported from corses-batches/Course_Batch_Merge (5).py', 'vyoma', false),
    ('course_catalogue_raw', 'Simple catalogue flatten, ported from corses-batches/course_catalogue_data (1).py', 'vyoma', false),
    ('students', 'Student roster sync, ported from ela_mis_datasets/edmingle_student_course_sync.py', 'vyoma', false),
    ('course_enrollments', 'Per-student course enrollment/attendance summary, ported from ela_mis_datasets/edmingle_student_course_sync.py', 'vyoma', false),
    ('enrollment_reports', 'Historical enrollment report export, ported from enrollments_reports/edmingle_export.py', 'vyoma', false)
ON CONFLICT (collector_name) DO UPDATE SET
    description = EXCLUDED.description,
    updated_at = now();

INSERT INTO system.pipelines (pipeline_name, description, is_enabled)
VALUES
    ('attendance', 'attendance -> bronze.report55_batch_attendance_summary / bronze.report55_session_attendance', false),
    ('catalogue', 'catalogue -> bronze.course_catalog', false),
    ('class_id_lookup', 'class_id_lookup -> bronze.class_id_lookup', false),
    ('class_session_attendance', 'class_session_attendance -> bronze.class_session_attendance', false),
    ('course_batch_merge', 'course_batch_merge -> bronze.course_batch_merge', false),
    ('course_catalogue_raw', 'course_catalogue_raw -> bronze.course_catalogue_raw', false),
    ('students', 'students -> bronze.students', false),
    ('course_enrollments', 'course_enrollments -> bronze.course_enrollments', false),
    ('enrollment_reports', 'enrollment_reports -> bronze.enrollment_reports', false)
ON CONFLICT (pipeline_name) DO UPDATE SET
    description = EXCLUDED.description;

COMMIT;
