-- Corrects the spelling of the courses_batches job family (previously
-- "corses_batches", introduced in migration 008) to match the corrected
-- folder name api_scripts/courses_batches/. Neither job has ever been run
-- (0 rows in bronze.course_batch_merge / bronze.course_catalogue_raw, no
-- audit.pipeline_runs history, no system.collection_checkpoints rows), so
-- this is a pure rename with no data to preserve under the old name.

UPDATE system.api_scripts
SET collector_name = 'courses_batches.course_batch_merge', updated_at = now()
WHERE collector_name = 'corses_batches.course_batch_merge';

UPDATE system.api_scripts
SET collector_name = 'courses_batches.course_catalogue_raw', updated_at = now()
WHERE collector_name = 'corses_batches.course_catalogue_raw';

UPDATE system.pipelines
SET pipeline_name = 'courses_batches.course_batch_merge'
WHERE pipeline_name = 'corses_batches.course_batch_merge';

UPDATE system.pipelines
SET pipeline_name = 'courses_batches.course_catalogue_raw'
WHERE pipeline_name = 'corses_batches.course_catalogue_raw';

UPDATE system.collection_checkpoints
SET collector_name = 'courses_batches.course_batch_merge'
WHERE collector_name = 'corses_batches.course_batch_merge';

UPDATE system.collection_checkpoints
SET collector_name = 'courses_batches.course_catalogue_raw'
WHERE collector_name = 'corses_batches.course_catalogue_raw';

UPDATE audit.pipeline_runs
SET pipeline_name = 'courses_batches.course_batch_merge'
WHERE pipeline_name = 'corses_batches.course_batch_merge';

UPDATE audit.pipeline_runs
SET pipeline_name = 'courses_batches.course_catalogue_raw'
WHERE pipeline_name = 'corses_batches.course_catalogue_raw';
