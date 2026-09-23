-- Migration 010: Silver models for the remaining single-source attendance
-- and enrollment Bronze tables.
-- Forward-only. Do not edit 001-009.
--
-- Per ROADMAP.md's own recommendation, confirmed by the project owner:
-- attendance and enrollment each have 2 Bronze sources measuring genuinely
-- different things at different grains, and are kept as SEPARATE Silver
-- entities rather than merged into one model each (unlike the courses
-- reconciliation in migration 009, which did pick one source). This
-- migration adds the 4 Silver tables that were still missing:
--   - silver.course_enrollments      <- bronze.course_enrollments
--   - silver.report55_batch_attendance_summary <- bronze.report55_batch_attendance_summary
--   - silver.report55_session_attendance       <- bronze.report55_session_attendance
--   - silver.class_session_attendance          <- bronze.class_session_attendance
-- silver.enrollment_reports already exists (migration 007) and is not
-- touched here.

BEGIN;

-- ---------------------------------------------------------------------
-- silver.course_enrollments  <- bronze.course_enrollments
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.course_enrollments (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id text NOT NULL,
    class_id text NOT NULL,
    name text,
    email text,
    class_name text,
    tutor_name text,
    total_classes integer,
    present_count integer,
    absent_count integer,
    late_count integer,
    excused_count integer,
    -- start_date/end_date/classusers_start_date/classusers_end_date/archived_at
    -- stay text, not date: the source API's exact date format for these
    -- fields has never been confirmed against a live sample (the Bronze
    -- collector itself only ever passed them through as plain text -- see
    -- api_scripts/ela_mis_datasets/course_enrollments/collector.py), so
    -- guessing a parse format here risks silently producing wrong dates.
    -- Revisit once a confirmed sample is available.
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
    source_updated_at timestamp with time zone,
    silver_updated_at timestamp with time zone NOT NULL DEFAULT now(),
    UNIQUE (user_id, class_id)
);
COMMENT ON TABLE silver.course_enrollments IS 'Typed/normalized pass over bronze.course_enrollments. Distinct from silver.enrollment_reports (different source, different grain) -- kept separate per project-owner decision, see ROADMAP.md.';

-- ---------------------------------------------------------------------
-- silver.report55_batch_attendance_summary  <- bronze.report55_batch_attendance_summary
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.report55_batch_attendance_summary (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    batch_id text NOT NULL,
    summary_window_start date NOT NULL,
    summary_window_end date NOT NULL,
    batch_name text,
    bundle_id text,
    bundle_name text,
    course_id text,
    course_name text,
    teacher_id text,
    teacher_name text,
    total_students_enrolled integer,
    first_class_date date,
    last_class_date date,
    first_class_attendance integer,
    last_class_attendance integer,
    total_present_marks integer,
    total_absent_marks integer,
    attendance_percentage numeric,
    average_class_attendance numeric,
    highest_class_attendance integer,
    lowest_class_attendance integer,
    average_rating numeric,
    retention_percentage numeric,
    attendance_drop integer,
    source_updated_at timestamp with time zone,
    silver_updated_at timestamp with time zone NOT NULL DEFAULT now(),
    UNIQUE (batch_id, summary_window_start, summary_window_end)
);
COMMENT ON TABLE silver.report55_batch_attendance_summary IS 'Typed pass over bronze.report55_batch_attendance_summary (report_type=55 pipeline). Distinct from silver.class_session_attendance (different endpoint, different grain) -- kept separate per project-owner decision, see ROADMAP.md.';

-- ---------------------------------------------------------------------
-- silver.report55_session_attendance  <- bronze.report55_session_attendance
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.report55_session_attendance (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    batch_id text NOT NULL,
    session_id text NOT NULL,
    batch_name text,
    course_id text,
    course_name text,
    session_number integer,
    class_date date,
    is_session_conducted boolean,
    present_count integer,
    absent_count integer,
    late_count integer,
    total_marked integer,
    session_attendance_percentage numeric,
    source_updated_at timestamp with time zone,
    silver_updated_at timestamp with time zone NOT NULL DEFAULT now(),
    UNIQUE (batch_id, session_id)
);
COMMENT ON TABLE silver.report55_session_attendance IS 'Typed pass over bronze.report55_session_attendance (report_type=55 pipeline). Distinct from silver.class_session_attendance (different endpoint, different grain) -- kept separate per project-owner decision, see ROADMAP.md.';

-- ---------------------------------------------------------------------
-- silver.class_session_attendance  <- bronze.class_session_attendance
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.class_session_attendance (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id text NOT NULL,
    class_id text,
    class_name text,
    master_batch_id text,
    master_batch_name text,
    bundle_id text,
    bundle_name text,
    class_date date,
    total_enrolled_at_session integer,
    present_count integer,
    not_marked_count integer,
    attendance_pct numeric,
    taken_by_name text,
    individual_batch_attendance text,
    session_start_ist timestamp without time zone,
    session_end_ist timestamp without time zone,
    session_duration_minutes numeric,
    is_session_conducted boolean,
    session_number integer,
    source_updated_at timestamp with time zone,
    silver_updated_at timestamp with time zone NOT NULL DEFAULT now(),
    UNIQUE (session_id)
);
COMMENT ON TABLE silver.class_session_attendance IS 'Typed pass over bronze.class_session_attendance (/organization/attendances pipeline). Distinct from silver.report55_session_attendance (different endpoint, different grain) -- kept separate per project-owner decision, see ROADMAP.md.';

INSERT INTO system.pipelines (pipeline_name, description, is_enabled)
VALUES
    ('silver_course_enrollments', 'silver_course_enrollments -> silver.course_enrollments (typed pass over bronze.course_enrollments)', false),
    ('silver_report55_batch_attendance_summary', 'silver_report55_batch_attendance_summary -> silver.report55_batch_attendance_summary (typed pass over bronze.report55_batch_attendance_summary)', false),
    ('silver_report55_session_attendance', 'silver_report55_session_attendance -> silver.report55_session_attendance (typed pass over bronze.report55_session_attendance)', false),
    ('silver_class_session_attendance', 'silver_class_session_attendance -> silver.class_session_attendance (typed pass over bronze.class_session_attendance)', false)
ON CONFLICT (pipeline_name) DO UPDATE SET
    description = EXCLUDED.description;

COMMIT;
