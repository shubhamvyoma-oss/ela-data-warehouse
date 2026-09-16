-- Migration 008: rename api_scripts registry entries to reflect the new
-- api_scripts/ layout (one top-level folder per original legacy source
-- folder, with a parent.job name for jobs living inside a multi-job
-- folder). Forward-only. Do not edit 001-007.
--
-- UPDATE, not delete+insert, so audit/checkpoint history tied to the same
-- row is preserved under the new name.

BEGIN;

UPDATE system.api_scripts SET collector_name = 'attendance_data.catalogue', updated_at = now()
    WHERE collector_name = 'catalogue';
UPDATE system.api_scripts SET collector_name = 'attendance_data.class_id_lookup', updated_at = now()
    WHERE collector_name = 'class_id_lookup';
UPDATE system.api_scripts SET collector_name = 'attendance_data.class_session_attendance', updated_at = now()
    WHERE collector_name = 'class_session_attendance';
UPDATE system.api_scripts SET collector_name = 'corses_batches.course_batch_merge', updated_at = now()
    WHERE collector_name = 'course_batch_merge';
UPDATE system.api_scripts SET collector_name = 'corses_batches.course_catalogue_raw', updated_at = now()
    WHERE collector_name = 'course_catalogue_raw';
UPDATE system.api_scripts SET collector_name = 'ela_mis_datasets.students', updated_at = now()
    WHERE collector_name = 'students';
UPDATE system.api_scripts SET collector_name = 'ela_mis_datasets.course_enrollments', updated_at = now()
    WHERE collector_name = 'course_enrollments';
-- 'attendance' and 'enrollment_reports' are unchanged (single-job folders).

UPDATE system.pipelines SET pipeline_name = 'attendance_data.catalogue'
    WHERE pipeline_name = 'catalogue';
UPDATE system.pipelines SET pipeline_name = 'attendance_data.class_id_lookup'
    WHERE pipeline_name = 'class_id_lookup';
UPDATE system.pipelines SET pipeline_name = 'attendance_data.class_session_attendance'
    WHERE pipeline_name = 'class_session_attendance';
UPDATE system.pipelines SET pipeline_name = 'corses_batches.course_batch_merge'
    WHERE pipeline_name = 'course_batch_merge';
UPDATE system.pipelines SET pipeline_name = 'corses_batches.course_catalogue_raw'
    WHERE pipeline_name = 'course_catalogue_raw';
UPDATE system.pipelines SET pipeline_name = 'ela_mis_datasets.students'
    WHERE pipeline_name = 'students';
UPDATE system.pipelines SET pipeline_name = 'ela_mis_datasets.course_enrollments'
    WHERE pipeline_name = 'course_enrollments';

-- Defensive: rename any checkpoint/run-history rows too, in case a dry run
-- left rows under the old names (no job has been run for real yet, but
-- this keeps the migration correct regardless).
UPDATE system.collection_checkpoints SET collector_name = 'attendance_data.catalogue'
    WHERE collector_name = 'catalogue';
UPDATE system.collection_checkpoints SET collector_name = 'attendance_data.class_id_lookup'
    WHERE collector_name = 'class_id_lookup';
UPDATE system.collection_checkpoints SET collector_name = 'attendance_data.class_session_attendance'
    WHERE collector_name = 'class_session_attendance';
UPDATE system.collection_checkpoints SET collector_name = 'corses_batches.course_batch_merge'
    WHERE collector_name = 'course_batch_merge';
UPDATE system.collection_checkpoints SET collector_name = 'corses_batches.course_catalogue_raw'
    WHERE collector_name = 'course_catalogue_raw';
UPDATE system.collection_checkpoints SET collector_name = 'ela_mis_datasets.students'
    WHERE collector_name = 'students';
UPDATE system.collection_checkpoints SET collector_name = 'ela_mis_datasets.course_enrollments'
    WHERE collector_name = 'course_enrollments';

UPDATE audit.pipeline_runs SET pipeline_name = 'attendance_data.catalogue'
    WHERE pipeline_name = 'catalogue';
UPDATE audit.pipeline_runs SET pipeline_name = 'attendance_data.class_id_lookup'
    WHERE pipeline_name = 'class_id_lookup';
UPDATE audit.pipeline_runs SET pipeline_name = 'attendance_data.class_session_attendance'
    WHERE pipeline_name = 'class_session_attendance';
UPDATE audit.pipeline_runs SET pipeline_name = 'corses_batches.course_batch_merge'
    WHERE pipeline_name = 'course_batch_merge';
UPDATE audit.pipeline_runs SET pipeline_name = 'corses_batches.course_catalogue_raw'
    WHERE pipeline_name = 'course_catalogue_raw';
UPDATE audit.pipeline_runs SET pipeline_name = 'ela_mis_datasets.students'
    WHERE pipeline_name = 'students';
UPDATE audit.pipeline_runs SET pipeline_name = 'ela_mis_datasets.course_enrollments'
    WHERE pipeline_name = 'course_enrollments';

COMMIT;
