# Enrollment reports API job

Ports `edmingle_export.py` / `edmingle_api.py` / `edmingle_chunker.py` (the standalone
enrollment-report export scripts) into this project. Collects Edmingle's row-level
enrollment report from
`GET /reports/enrollment` (params `report_details_type: 3`, `time_step: 1`,
`sort_order: "D"`, `sort_by: "date_of_enrolment"`, `currency_id: 1`; `apikey` / `ORGID`
headers are set globally by `EdmingleApiClient`), pulled in `<= chunk_days`-day date
windows and upserted into `bronze.enrollment_reports`.

## Distinct data source from `bronze.course_enrollments`

This is **not** the same job as `course_enrollments`. They port different original
scripts, hit different endpoints, and populate different tables:

| | `enrollment_reports` (this job) | `course_enrollments` |
|---|---|---|
| Original script | `edmingle_export.py` | `edmingle_student_course_sync.py` |
| Endpoint | `GET /reports/enrollment` | `GET /admin/classes/attendance` |
| Shape | One row per enrollment event, for a date range | One row per (student, class) attendance summary |
| Table | `bronze.enrollment_reports` | `bronze.course_enrollments` |

## Date window: own chunking logic, kept out of `common/`

Required env vars (no defaults -- matches the original script's required
`--start-date`/`--end-date` CLI flags):

- `ENROLLMENT_REPORTS_START_DATE` -- `DD-MM-YYYY`
- `ENROLLMENT_REPORTS_END_DATE` -- `DD-MM-YYYY`

Optional:

- `ENROLLMENT_REPORTS_CHUNK_DAYS` -- default `30`, matching the original's default.
- `ENROLLMENT_REPORTS_PER_PAGE` -- default `100`. Not one of the original script's env
  vars (it read `per_page` out of a job-specific `edmingle_config.json` instead); this
  port has no equivalent config file, so it becomes an env var with a default matching
  the `students_per_page`/`batches_per_page` defaults already used elsewhere in
  `EdmingleSettings`.

`build_chunks(start_date, end_date, chunk_days)` in `enrollments_reports_collector.py` splits that inclusive
range into windows of at most `chunk_days` days each -- ported near-verbatim from the
original `edmingle_chunker.build_chunks` (the only change: raising `ValueError` instead
of calling `sys.exit()`, since this runs inside a collector rather than a standalone CLI
script).

Per this project's decision, this chunking logic stays local to this job rather than
folding into `api_scripts/common/`. It is genuine business logic -- how the date range
gets partitioned into request windows, because Edmingle rejects overly large single-shot
ranges -- not shared HTTP mechanics like retries or pagination, so there is nothing
reusable here for other jobs to share.

## What the shared `EdmingleApiClient` supersedes

The original `edmingle_api.fetch_page` hand-rolled its own `RollingRateLimiter`,
exponential backoff, and permanent-vs-transient HTTP status classification. None of
that is ported: `runtime.client.get_json()` (the shared `EdmingleApiClient`) already
retries transient errors with backoff, rate-limits requests, and raises on permanent
HTTP errors. This job only adds back the one check `get_json()` doesn't already cover --
the original's explicit `data["code"] == 200` validation on top of Edmingle's own
`error_code` 6001/6002 checks -- and the `studentlist` list-shape validation, via the
shared `require_record_list()` helper.

## Field mapping and `NULL` handling

`COLUMNS` in `enrollments_reports_collector.py` is a direct 1:1 port of `FIELDS` from the original
`edmingle_constants.py` -- same 22 columns, same order. Extra API fields are dropped;
a field missing from a `studentlist` row is treated the same as one present with a
`None` value.

The original CSV writer turned `None` into an empty string (a CSV-specific convention)
and implicitly stringified any non-string value (e.g. a list/dict field) via
`csv.DictWriter`. Since every column in `bronze.enrollment_reports` is `text`:

- `None` stays `NULL` -- the CSV convention doesn't apply to a `text` column.
- Any non-string, non-`None` value (e.g. `batch_ids`, `shipping_details_json` returned
  as a list/dict) is passed through Python's `str()`, reproducing exactly what
  `csv.DictWriter` would have written, rather than reformatting it as JSON.

## Checkpointing: per chunk, not per page

The original script checkpointed after every single page (byte-offset truncation into
a CSV, to survive a crash mid-page). This port batches all pages of a chunk into one
`commit_rows()` call, checkpointing `{"chunks_completed": N, "total_chunks": M,
"updated_at": ...}` once per completed chunk. `bronze.enrollment_reports` has a
`UNIQUE (enrollment_id)` constraint, so a crash mid-chunk just means the next run
re-fetches and re-upserts that one chunk -- no risk of duplicate rows, and no need for
byte-offset-precision resume.

## Other deviations from the original script

- No email alerting (startup checks, failure/status emails) is ported -- that belongs
  to the shared runner/observability layer (`audit.pipeline_runs`, `audit.events`), not
  to an individual collector.
- No standalone `.chunks.json` plan file -- `build_chunks()` is cheap to recompute, so
  it is simply called again on every run rather than persisted and reloaded.

## Status (updated 2026-09-23)

Registered in `api_scripts/runner.py`'s `collector_registry()` as `enrollment_reports`, with
`TransformedTableRepository` wired into the `CollectorRuntime` the runner constructs. Runnable
via `python warehouse_cli.py collect enrollment_reports`. It stays `is_enabled: false` in
`services/scheduler/jobs.example.yaml` (as does every job in this repo) -- that flag, not
registry wiring, is what gates it from running against the live Edmingle API and spending real
credits.
