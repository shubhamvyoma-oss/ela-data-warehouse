# Course enrollments API job

Collects the course/enrollment half of the legacy `edmingle_student_course_sync.py`
script (the student-roster half is ported separately as the `students` job, its own
job in this project). For every eligible student, one call to
`GET /admin/classes/attendance` (params `user_id`, `response_type: 1`; `apikey` /
`ORGID` headers are set globally by `EdmingleApiClient`) returns that student's
`classes` list -- a set of per-class enrollment/attendance-summary rows -- which is
upserted into `bronze.course_enrollments`.

## Dependency: requires `students` to have run first

This job does not carry its own student list or CSV snapshot. It reads the eligible
`user_id`s straight from `bronze.students`, the table the `students` job populates:

```sql
SELECT DISTINCT user_id FROM bronze.students
WHERE user_id IS NOT NULL AND user_id <> 'NA'
ORDER BY user_id
```

(`user_id <> 'NA'` reproduces the original script's `_valid_course_users` filter,
which excluded students without a real Edmingle user_id. The `ORDER BY` is an addition
over the literal query, added so the `students_processed` checkpoint below resumes
against a stable, repeatable ordering rather than whatever order Postgres happens to
return rows in.)

If `students` has not run yet, `bronze.students` is empty and this job simply commits
an empty batch and records a checkpoint -- it does no harm, it just does nothing. This
mirrors this project's existing pattern of a downstream job reading an upstream job's
already-committed Bronze table instead of re-deriving the list itself (e.g.
`class_id_lookup` depending on `catalogue`).

Because `CollectorRuntime` has no generic query method, this collector opens its own
short-lived `Database(DatabaseSettings.from_environment(), "course_enrollments-lookup")`
connection inside `run()` purely to read `bronze.students`, separate from whatever
connection the runtime uses internally to write via `commit_rows()`.

## Simplification vs. the original script

The original `edmingle_student_course_sync.py` rebuilt the entire course-enrollment
CSV as one full snapshot on every run: it took a snapshot of the student list, wrote
class rows to an `.in_progress.csv` file, fsync'd and checkpointed the byte offset
after every single student, and only atomically renamed the file into place once the
whole snapshot finished -- all to guarantee it never published a half-written file
across an ~80-hour run.

That machinery isn't needed here. `bronze.course_enrollments` has a
`UNIQUE (user_id, class_id)` constraint, so each student's rows can simply be upserted
as they're fetched -- a crash mid-run just means the next run re-fetches a handful of
already-upserted students, which the unique constraint absorbs for free. Progress is
tracked with a plain `{"students_processed": N, "updated_at": ...}` checkpoint instead
of a resumable byte offset, and rows are batched into `commit_rows()` every 100
students (a minor implementation choice for transaction overhead, not a fidelity
requirement) rather than one commit per student. The `students` job, ported
separately, makes the same simplification for the same reason.

## Other deviations from the original script

- **name / email columns**: the original attached `name`/`email` to every class row
  from the student-master CSV row for that user_id. Since this job's input is now just
  a `user_id` list (per the dependency query above, which intentionally selects only
  `user_id` -- `bronze.students` is an append-only Bronze table and may hold more than
  one historical row per user_id, so there is no single unambiguous name/email to join
  against without additional logic), `name`/`email` are populated only if the
  `/admin/classes/attendance` response itself includes those fields on a class row;
  otherwise they are left `NULL`. This is a minor fidelity gap versus the original,
  called out explicitly here rather than silently joining against an arbitrary
  `bronze.students` row.
- **Missing `class_id`**: `bronze.course_enrollments.class_id` is `NOT NULL`. The
  original script had no such constraint (CSV). If the API ever returns a class entry
  without a `class_id`, this collector skips just that row (rather than failing the
  whole batch) so one malformed entry can't block every other student in the batch.
- No email alerting (startup checks, failure/status emails) is ported -- that
  belongs to the shared runner/observability layer (`audit.pipeline_runs`,
  `audit.events`), not to an individual collector.

## Status (updated 2026-09-23)

Registered in `api_scripts/runner.py`'s `collector_registry()` as
`ela_mis_datasets.course_enrollments`, with `TransformedTableRepository` wired into the
`CollectorRuntime` `run_collector()` constructs. Runnable via `python warehouse_cli.py collect
ela_mis_datasets.course_enrollments`. It stays `is_enabled: false` in
`services/scheduler/jobs.example.yaml` (as does every job in this repo) -- that flag, not
registry wiring, is what gates it from running against the live Edmingle API.
