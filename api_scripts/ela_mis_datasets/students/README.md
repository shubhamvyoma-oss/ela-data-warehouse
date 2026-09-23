# Students API job

Collects the Edmingle student roster from
`GET /organization/students?organization_id={organization_id}&is_archived=0&per_page={per_page}&page={page}`.

This fills the previously-reserved `students/` job folder. It is one half of the legacy
`edmingle_student_course_sync.py` script (formerly run standalone on the VPS): that script did
two things in one ~68-80 hour run -- sync the student roster, then walk every student to pull
course/class attendance. This job ports only the **student roster** half. The **course /
enrollment** half is ported separately into `api_scripts/ela_mis_datasets/course_enrollments/` as its own job.

## Response contract

The confirmed response shape is a top-level `students` list, including a valid empty list, which
signals the last page. Pagination stops on the first page that returns zero students.

## Custom fields

Each student record carries a `customfield_data` list where a handful of registration fields are
stored **by position**, not by name (copied from the original script's
`index_mapping = {"PhoneNumber": 19, "Age": 9, "LastName": 6, "UserName": 0}`):

| Bronze column       | Custom field  | `customfield_data` index |
|----------------------|---------------|---------------------------|
| `custom_phone_number` | PhoneNumber   | 19                        |
| `custom_age`           | Age           | 9                         |
| `custom_last_name`     | LastName      | 6                         |
| `custom_user_name`     | UserName      | 0                         |

A short or missing `customfield_data` list (or a non-dict entry at that index) is treated as
`None` rather than raising.

## Storage and dedupe

Rows are upserted into `bronze.students` via `CollectorRuntime.commit_rows(...)`, which uses the
table's existing `UNIQUE (user_id)` constraint to do `ON CONFLICT (user_id) DO UPDATE SET
<every other column>` -- i.e. the newest fetched row for a `user_id` always wins. This reproduces
the original script's `merge_students()` dedupe-by-`user_id`, last-write-wins behavior, but as a
database upsert instead of an in-memory dict merge over a CSV file.

Rows are committed once per fetched page (not batched to the end), so a crash mid-run does not
lose already-fetched pages -- matching the original script's intent of surviving interruption
without a full restart.

## Simplification: no page-overlap resume

The original script tracked `last_completed_student_page` and re-fetched `overlap_pages` pages
before that point on each run, to catch students who registered while the previous run was still
in progress. That mechanism existed because the original script's single run took days and wrote
to a local CSV with no per-row upsert guarantee.

This port simplifies that away: **every run starts from page 1** and walks through to the first
empty page. Because every row is upserted idempotently via `ON CONFLICT (user_id) DO UPDATE`, a
full re-fetch on each run is safe and self-healing -- there is no resume-window gap to cover, and
no separate overlap bookkeeping to maintain. The `checkpoint` argument passed into `run()` is
therefore informational only (bookkeeping for observability) and is not used to pick a starting
page.

The checkpoint written on each page commit is:

```json
{"last_page_fetched": 3, "total_students_seen": 1500, "updated_at": "2026-09-16T12:00:00+00:00"}
```

## Configuration

| Env var             | Default | Notes                                                        |
|----------------------|---------|---------------------------------------------------------------|
| `STUDENTS_PER_PAGE`   | `500`   | Job-specific page size, matching the original config's `students_per_page`. Falls back to the default on missing/invalid values. |

Auth (`apikey`, `ORGID`) and `organization_id` come from `EdmingleSettings.from_environment()`,
shared with every other collector in `api_scripts/`.

## Status (updated 2026-09-23)

Registered in `api_scripts/runner.py`'s `collector_registry()` as `ela_mis_datasets.students`,
with `TransformedTableRepository` wired into the `CollectorRuntime` `run_collector()`
constructs. Runnable via `python warehouse_cli.py collect ela_mis_datasets.students`. It stays
`is_enabled: false` in `services/scheduler/jobs.example.yaml` (as does every job in this repo)
-- that flag, not registry wiring, is what gates it from running against the live Edmingle API.
