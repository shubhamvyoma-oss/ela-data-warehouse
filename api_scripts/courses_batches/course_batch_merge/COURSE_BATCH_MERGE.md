# Course Batch Merge Job

## 1. Overview

`CourseBatchMergeJob` (registered job name `courses_batches.course_batch_merge`) is a
full-refresh Bronze job that reproduces the legacy standalone script
`Course_Batch_Merge.py`. On every run it fetches the entire Edmingle institute course
catalogue and every batch across all three lifecycle statuses (Active, Archived,
Completed), merges the two into one wide, denormalized table, and writes the result to
`bronze.course_batch_merge`. It is one of nine jobs in `api_scripts/` that port a legacy
`ela_datasets` pipeline into this project's checkpointed, audited job framework, writing
to Postgres instead of CSV.

**Current status: disabled, never run against the live API.** `bronze.course_batch_merge`
has 0 rows (confirmed via direct query on 2026-09-24), `system.collection_checkpoints`
has no row for this job, and `audit.pipeline_runs` has no entry for pipeline_name
`courses_batches.course_batch_merge`. The job is registered and importable, but it has
never executed end to end against the live Edmingle API.

## 2. Purpose

Downstream Silver/Gold reporting on "what courses and batches exist, and which batch is
the current one for each course" needs a single denormalized view that combines the
institute catalogue (course-level metadata) with the batch/class list (schedule,
tutor, enrollment counts) and derives which batch is the latest per course. This job
exists to produce exactly that table, replacing the legacy script's manually-run,
CSV-based version of the same computation. Per `processing/silver/courses.py`, this
Bronze table is the sole confirmed source for `silver.courses`.

## 3. High-Level Data Flow

```mermaid
flowchart LR
    A[Edmingle API] -->|GET /institute/{id}/courses/catalogue| B[CourseBatchMergeJob]
    A -->|GET /short/masterbatch status=0,1,3, paginated| B
    B -->|pandas merge + business rules| C[JobRuntime.commit_rows]
    C --> D[TransformedTableRepository]
    D --> E[(bronze.course_batch_merge)]
    E -->|FROM bronze.course_batch_merge, excludes Archived| F[(silver.courses)]
```

`processing/silver/courses.py` confirms the Silver edge: its `_SELECT_SQL` reads
`FROM bronze.course_batch_merge` directly (excluding `batch_status = 'Archived'` rows),
making `bronze.course_batch_merge` the single reconciled source for `silver.courses`,
in preference to the older `bronze.course_catalog` and the sibling
`bronze.course_catalogue_raw` table.

## 4. Project / Repository Structure

```
api_scripts/
├── common/
│   ├── models.py            # RawRecord, JobStats, canonical_json/payload_sha256 helpers
│   ├── runtime.py           # JobRuntime (commit / commit_rows)
│   ├── api_client.py        # EdmingleApiClient (retry, backoff, rate limit)
│   ├── repositories.py      # BronzeRepository, CheckpointRepository, RunRepository, TransformedTableRepository
│   └── edmingle.py          # require_record_list, find_record_list, flatten_master_batches, has_more_pages
├── runner.py                 # job_registry(), run_job() -- CLI entry point plumbing
└── courses_batches/
    └── course_batch_merge/
        ├── __init__.py
        ├── README.md
        ├── course_batch_merge.py   # CourseBatchMergeJob
        └── COURSE_BATCH_MERGE.md   # this file
shared/
├── config/settings.py        # DatabaseSettings, WarehouseSettings, EdmingleSettings
└── database.py                # Database (connection/transaction context managers)
services/scheduler/jobs.example.yaml  # scheduler job list (all is_enabled: false)
```

## 5. Source System

| Source | Type | Endpoint | HTTP Method | Authentication | Parameters | Pagination | Rate Limit |
|---|---|---|---|---|---|---|---|
| Edmingle catalogue | REST/JSON | `/institute/{institute_id}/courses/catalogue` | GET | `apikey` + `ORGID` headers (`EdmingleSettings`) | `institution_id` | None (single call) | Shared `EdmingleApiClient` rate limiter (`EDMINGLE_MIN_REQUEST_INTERVAL_SECONDS`, default 2.5s) |
| Edmingle master batches | REST/JSON | `/short/masterbatch` | GET | `apikey` + `ORGID` headers | `status` (0/1/3), `page`, `per_page=1000` (hardcoded), `organization_id` | Manual: loop per status code, stop when returned `courses` list is shorter than `per_page` | Same shared rate limiter; retries on HTTP 429/5xx with exponential backoff |

## 6. Extraction Process

1. Read `EDMINGLE_INSTITUTE_ID` and `organization_id` off `runtime.client.settings`;
   raise `ValueError` immediately if the institute ID is missing.
2. `_fetch_catalogue()` — one GET to the catalogue endpoint. If the `response` list is
   empty, raise `ApiContractError` (mirrors the legacy script's "Catalogue fetch failed.
   Aborting.").
3. `_fetch_batches()` — for each of the three status codes (`0` Active, `1` Archived,
   `3` Completed), page through `/short/masterbatch` with `per_page=1000` until a page
   returns fewer courses than `per_page`. Each course's `batch` list (defaulting to
   `[{}]` if absent, to preserve a placeholder row) is flattened into one row per
   `(bundle_id, batch)` pair. If no rows are collected across all statuses, raise
   `ApiContractError`.
3. Both fetches use the shared `EdmingleApiClient.get_json()`, which already retries
   transient network errors and HTTP 429/5xx with backoff, and raises
   `ApiRequestError`/`ApiContractError` on non-retriable failures.

## 7. Detailed Function Documentation

| Function | Responsibility |
|---|---|
| `CourseBatchMergeJob.run(runtime, checkpoint)` | Orchestrates the full 11-step pipeline described in section 9 and calls `runtime.commit_rows()` once at the end. |
| `_fetch_catalogue(runtime, institute_id)` | Single GET to the catalogue endpoint; returns a `pandas.DataFrame`. Raises if empty. |
| `_fetch_batches(runtime, organization_id)` | Paginated GET across 3 batch statuses; returns a flattened `pandas.DataFrame`. Raises if empty. |
| `_filter_test_batches(df)` | Drops rows whose `batch_name` contains "test batch" (case-insensitive). |
| `_compute_bundle_enrollment(df)` | Adds `bundle_enrollment_count` = sum of `batch_enrollment_count` grouped by `bundle_id`. |
| `_mark_latest_batch(df)` | Sorts by `(bundle_id, start_date desc, batch_id desc)` and flags the first row per bundle as `Is_Latest_Batch = 1`. |
| `_filter_test_courses(df)` | Drops rows where `Catalogue_Match == 0` AND `bundle_name` contains a test/demo/dummy/sample/etc. keyword. |
| `_apply_business_logic(df)` | Derives `Catalogue_Status` (mirror of raw `Status`) and `Final_Status` (latest batch inherits catalogue `Status` if valid, else blank; non-latest batches default to `"Completed"`). |
| `_add_courses_without_batches(merged_df, cat_df)` | Appends one synthetic row per catalogue bundle with no batch at all (`Has_Batch = 0`, batch-only columns set to `None`). |
| `_format_dates(df)` | Converts Unix-epoch `start_date`/`end_date` to `date` objects. |
| `_build_rows(df)` / `_FIELD_MAP` | Maps the final DataFrame to a fixed, ordered list of `(target_column, source_column, caster)` tuples and builds row tuples for insertion. |
| `_clean_text` / `_clean_numeric` / `_clean_bool` / `_clean_date` | Null-safe type casters used by `_FIELD_MAP`, handling `None` and `pandas.NaT`/`NaN`. |

## 8. Input Parameters & Configuration

| Env var | Required | Default | Notes |
|---|---|---|---|
| `EDMINGLE_INSTITUTE_ID` | Yes | — | Job raises `ValueError` if unset/blank. |
| `EDMINGLE_ORGANIZATION_ID` | Yes (via `EdmingleSettings`) | — | Used as `organization_id` in the batches request. |
| `EDMINGLE_API_KEY` | Yes | — | Sent as `apikey` header by `EdmingleApiClient`. |
| `EDMINGLE_API_BASE_URL` | No | `https://vyoma-api.edmingle.com/nuSource/api/v1` | |
| `EDMINGLE_MIN_REQUEST_INTERVAL_SECONDS` | No | `2.5` | Shared client-side rate limit. |
| `EDMINGLE_MAX_RETRIES` | No | `4` | Shared retry budget. |

There is no job-specific `per_page` env var for batches — `_BATCHES_PER_PAGE = 1000` is
hardcoded, intentionally diverging from the sibling `batches` job's configurable
`EDMINGLE_BATCHES_PER_PAGE`.

## 9. Data Transformation

The transform is an 11-step pipeline executed in `run()`, in order: (1) fetch catalogue,
(2) fetch batches, (3) filter test batches, (4) compute `bundle_enrollment_count`,
(5) mark `Is_Latest_Batch`, (6) set `Has_Batch = 1`, (7) left-merge batches onto
catalogue via `bundle_id` == `Bundle id`, (8) filter test/junk courses, (9) apply
`Final_Status`/`Catalogue_Status` business logic, (10) append catalogue-only synthetic
rows, (11) format dates and build output rows. This is a line-for-line port of the
legacy script's logic — see inline comments in `course_batch_merge.py` for the exact
rules preserved (including the `"Tutord Ids"` typo carried over verbatim from the
source data, mapped to the `tutor_ids` column).

## 10. Output Dataset

Table: `bronze.course_batch_merge`. One row per `(batch_id, bundle_id)` pair, plus one
synthetic row per catalogue bundle that has no batch at all. Full-refresh: every run
re-derives and re-writes the complete dataset from scratch (no incremental logic).

## 11. Output Schema

Confirmed live via `psql -c "\d bronze.course_batch_merge"` on 2026-09-24:

| Column | Data Type | Description | Source/Derived |
|---|---|---|---|
| `id` | bigint (identity) | Surrogate primary key | Generated by Postgres |
| `pipeline_run_id` | uuid, not null, FK → `audit.pipeline_runs(id)` | Run that wrote/last-touched the row | `JobRuntime` |
| `bundle_id` | text | Course/bundle identifier | API: catalogue `Bundle id` / batch `bundle_id` |
| `bundle_name` | text | Course/bundle name | API |
| `batch_id` | text | Batch/class identifier (NULL for catalogue-only synthetic rows) | API: `class_id` |
| `batch_name` | text | Batch/class name | API: `class_name` |
| `batch_status` | text | `Active` / `Archived` / `Completed` | Derived from the fetch status code |
| `start_date` | date | Batch start date | Derived from Unix epoch `start_date` |
| `end_date` | date | Batch end date | Derived from Unix epoch `end_date` |
| `tutor_name` | text | Tutor name | API |
| `tutor_id` | text | Tutor identifier | API |
| `batch_enrollment_count` | numeric | Per-batch admitted student count | API: `admitted_students` |
| `course_name` | text | Catalogue course name | API |
| `tutors` | text | Catalogue tutors field | API |
| `tutor_ids` | text | Catalogue tutor IDs (source field literally named `"Tutord Ids"`) | API |
| `course_ids` | text | Catalogue course IDs | API |
| `subject` | text | Catalogue subject | API |
| `level` | text | Catalogue level | API |
| `language` | text | Catalogue language | API |
| `examination` | text | Catalogue examination field | API |
| `course_type` | text | Catalogue `Type` field | API |
| `course_division` | text | Catalogue course division | API |
| `certificate` | text | Catalogue certificate field | API |
| `course_sponsor` | text | Catalogue sponsor field | API |
| `course_title_sanskrit` | text | Catalogue Sanskrit title | API |
| `catalogue_raw_status` | text | Raw catalogue `Status` field, unmodified | API |
| `number_of_lectures` | text | Catalogue field | API |
| `duration` | text | Catalogue field | API |
| `personas` | text | Catalogue field | API |
| `computer_based_assessment` | text | Catalogue field | API |
| `product_id` | text | Catalogue field | API |
| `sss_category` | text | Catalogue field | API |
| `viniyoga` | text | Catalogue field | API |
| `adhyayanam_category` | text | Catalogue field | API |
| `term_of_course` | text | Catalogue field | API |
| `position_in_funnel` | text | Catalogue field | API |
| `division` | text | Catalogue field | API |
| `is_catalogue_match` | boolean | Whether the batch row matched a catalogue bundle | Derived |
| `bundle_enrollment_count` | numeric | Sum of `batch_enrollment_count` per bundle | Derived |
| `is_latest_batch` | boolean | Whether this is the most recent batch for its bundle | Derived |
| `has_batch` | boolean | `0` for synthetic catalogue-only rows, else `1` | Derived |
| `catalogue_status` | text | Mirror of `Status` at merge time | Derived |
| `final_status` | text | Business-rule-derived final status | Derived |
| `received_at` | timestamptz, not null | When the row was received by the job | `TransformedTableRepository` |
| `created_at` | timestamptz, not null, default `now()` | Row insert time | Postgres default |

Constraints: `PRIMARY KEY (id)`; `UNIQUE (batch_id, bundle_id)`; FK `pipeline_run_id` →
`audit.pipeline_runs(id)`.

## 12. Data Quality & Validation

- Both fetch functions raise `ApiContractError` if the API returns zero rows, aborting
  the entire run rather than writing a partial/empty full-refresh (mirrors the legacy
  script's abort-on-empty-fetch behavior).
- `require_record_list()` (via `_fetch_catalogue`/inline checks) validates that expected
  keys are lists of dicts before processing.
- Casters (`_clean_text`, `_clean_numeric`, `_clean_bool`, `_clean_date`) null-safely
  handle `pandas.NaT`/`NaN` so malformed/missing values become SQL `NULL` rather than
  raising or inserting the string `"nan"`.
- No row-level rejection counter is used in this job; a malformed row is more likely to
  raise (via `_clean_numeric`'s `int()` cast) than to be silently dropped.

## 13. Error Handling & Logging

- `ApiContractError` (from `api_scripts.common.api_client`) is raised on empty
  catalogue/batch fetches, an unexpected HTTP response, or Edmingle's own
  `error_code` 6001/6002 embedded in a 200 response.
- `ApiRequestError` is raised for HTTP 400/401/403/404 (no retry) and for exhausted
  retries on 429/5xx or network timeouts.
- All logging goes through the standard `logging` module under logger names
  `warehouse.job` / `warehouse.api` / `warehouse.runner`; `runner.run_job()` logs
  `"job succeeded"` or `"job failed"` with `job`, `run_id`, `rows_read`, `rows_written`,
  `request_count`.
- On any unhandled exception inside `job.run()`, `runner.run_job()` catches it, calls
  `RunRepository.finish(..., status="failed", error_category=type(exc).__name__)`, and
  returns exit code `1`. The error message stored is the generic
  `"job failed; inspect protected application logs"` — actual exception text is not
  persisted to the database.

## 14. Dependencies

- Python: `pandas`, `numpy` (listed in `requirements.txt`), `psycopg2` (via
  `TransformedTableRepository`), `requests` (via `EdmingleApiClient`).
- Internal: `api_scripts.common.{api_client,edmingle,models,repositories,runtime}`,
  `shared.config`, `shared.database`.
- Upstream data dependency: none (this job fetches everything itself; unlike
  `course_enrollments`, it does not read another job's Bronze table).

## 15. Setup

1. Ensure `.env` (or equivalent environment) defines `EDMINGLE_API_KEY`,
   `EDMINGLE_ORGANIZATION_ID`, `EDMINGLE_INSTITUTE_ID`, and the standard
   `WAREHOUSE_DB_*` variables (see `shared/config/settings.py`) — variable names only,
   actual values are never printed here.
2. Apply database migrations (`python warehouse_cli.py migrate`) so `bronze.course_batch_merge`,
   `system.collection_checkpoints`, and `audit.pipeline_runs` exist.
3. Confirm `pandas`/`numpy` are installed (`requirements.txt`).

## 16. How to Run

Exact registered job-name string, confirmed from `api_scripts/runner.py::job_registry()`:
**`courses_batches.course_batch_merge`**.

```bash
python warehouse_cli.py collect courses_batches.course_batch_merge
python warehouse_cli.py collect courses_batches.course_batch_merge --run-type scheduled
```

`warehouse_cli.py`'s `collect` subcommand calls `api_scripts.runner.run_job(job, run_type)`
directly; there is no separate script entry point for this job.

## 17. Database / Warehouse Integration

- **Schema/table**: `bronze.course_batch_merge` (see section 11).
- **Checkpoint mechanism**: `system.collection_checkpoints`, keyed on
  `(job_name="courses_batches.course_batch_merge", partition_key="default")`. The
  checkpoint payload is informational only — `{"completed_at": ..., "row_count": ...}`
  — since this is a full-refresh job with no incremental resume logic. Confirmed via
  query: **0 rows currently exist in `system.collection_checkpoints`** for this job,
  because it has never run.
- **Audit trail**: `audit.pipeline_runs` (one row per `run_job()` invocation, via
  `RunRepository`) and `audit.events` (`job_started`, `checkpoint_committed`,
  `job_finished`/`job_failed`). Confirmed via query: **no rows exist in
  `audit.pipeline_runs` for `pipeline_name = 'courses_batches.course_batch_merge'`**.
- **Upsert behavior**: `TransformedTableRepository.write_with_checkpoint()` does
  `INSERT ... ON CONFLICT (batch_id, bundle_id) DO UPDATE SET <all other columns>`.
- **Primary/unique keys**: `id` (surrogate PK), `UNIQUE (batch_id, bundle_id)`.

## 18. Automation / Scheduling

Confirmed from `services/scheduler/jobs.example.yaml`: this job has an entry
(`courses_batches_course_batch_merge_weekly`, `job_key: courses_batches.course_batch_merge`,
`interval_minutes: 10080`) but with **`is_enabled: false`**, same as every job in that
file. Confirmed from `shared/config/settings.py`: `WarehouseSettings.scheduler_enabled`
defaults to `False` (`WAREHOUSE_SCHEDULER_ENABLED`). Confirmed on the VPS: no systemd
unit or running process matching the scheduler was found, and the only crontab entry on
the host runs `python warehouse_cli.py transform enrollments` (a Silver transform) every
minute — it does not invoke this or any other `collect` job. **The scheduler service
itself is not currently deployed, and this job is not run by any automation on the VPS.**

## 19. Data Lineage

`Edmingle API (catalogue + masterbatch endpoints)` → `CourseBatchMergeJob` (pandas
merge/transform) → `bronze.course_batch_merge` → `silver.courses` (confirmed:
`processing/silver/courses.py` selects `FROM bronze.course_batch_merge`, excluding
`batch_status = 'Archived'`). No Gold-layer consumer was identified in the current
implementation.

## 20. Important Business / Technical Rules

- Archived batches are deliberately **not** dropped at this layer (unlike the sibling
  `batches` job) because `Is_Latest_Batch` needs the full batch history per bundle.
- `Final_Status` defaults to `"Completed"` for every non-latest batch, regardless of its
  actual status.
- Test/demo/junk filtering only drops a row when there is **no** catalogue match AND the
  name contains a keyword — a real catalogue-matched course named e.g. "Sample Course"
  would NOT be dropped.
- The `"Tutord Ids"` source field name (a typo in the upstream API/script) is mapped
  intentionally, verbatim, to the `tutor_ids` column.

## 21. Known Limitations

### Confirmed limitations
- **Disabled / never run against the live API.** Confirmed by: `bronze.course_batch_merge`
  row count = 0; `system.collection_checkpoints` has no row for this job;
  `audit.pipeline_runs` has no row for `pipeline_name = 'courses_batches.course_batch_merge'`;
  `is_enabled: false` in `services/scheduler/jobs.example.yaml`.
- **`NULL` batch_id rows never upsert across runs.** Synthetic catalogue-only rows have
  `batch_id = NULL`; Postgres never treats two `NULL`s as equal for the
  `UNIQUE (batch_id, bundle_id)` constraint, so each full-refresh run inserts a fresh
  copy of every catalogue-only row instead of updating the previous run's row — a
  property of the pre-existing table definition, documented in the job's own README.
- Full-refresh design means there is no true incremental/delta collection; every run
  re-fetches the entire catalogue and batch universe.

### Requires confirmation
- Expected run duration and API request volume against the live Edmingle API have not
  been measured, since the job has never been run.
- Whether `bronze.course_catalog` (the older raw-mirror table referenced in
  `processing/silver/courses.py`'s docstring) is still populated by any active job is
  outside the scope of this document — requires confirmation from the project owner.

## 22. Troubleshooting

| Symptom | Likely cause | Where to look |
|---|---|---|
| `ValueError: EDMINGLE_INSTITUTE_ID is required...` | Env var missing/blank | `.env` / deployment environment |
| `ApiContractError: ...catalogue returned no rows; aborting...` | Catalogue endpoint returned an empty `response` list | Edmingle API status, `EDMINGLE_INSTITUTE_ID` correctness |
| `ApiContractError: ...batches fetch returned no rows; aborting...` | `/short/masterbatch` returned no courses for any status | `EDMINGLE_ORGANIZATION_ID` correctness, API availability |
| `ApiRequestError: ... returned HTTP 401/403` | Invalid/expired API key | `EDMINGLE_API_KEY`, `ApiKeyLifecycle` status |
| Job exits 1 with `error_category` in `audit.pipeline_runs` | Any unhandled exception in `run()` | Application logs (message itself is redacted in the DB) |

## 23. Maintenance Guide

- Business-logic changes should be cross-checked against the original
  `Course_Batch_Merge.py` script before altering `_FIELD_MAP` or the transform steps —
  the job is explicitly documented as a 1:1 port.
- If `bronze.course_batch_merge`'s schema changes, update `_FIELD_MAP` (column order
  must match `COLUMNS` passed to `commit_rows()`).
- Before enabling in production, flip `is_enabled: true` for this job's entry in a
  deployed copy of `services/scheduler/jobs.example.yaml` (the `.example.` file itself
  is a template, not live config) and deploy/start the scheduler service, which does
  not currently run anywhere.

## 24. Upstream & Downstream Dependencies

- **Upstream**: Edmingle catalogue and masterbatch REST endpoints only; no dependency on
  any other job's Bronze table.
- **Downstream**: `silver.courses` (confirmed, via `processing/silver/courses.py`).

## 25. Security Considerations

- API credentials (`EDMINGLE_API_KEY`, `EDMINGLE_ORGANIZATION_ID`) are read from
  environment variables only, never logged or embedded in code (see
  `EdmingleSettings.redacted_summary()` for the safe-to-log projection).
- Database credentials (`WAREHOUSE_DB_PASSWORD`, etc.) are likewise environment-only.
- `ApiRequestError` messages are deliberately constructed to exclude response bodies and
  request URLs, per the class's docstring, to avoid leaking sensitive payloads into logs.
- Failure records in `audit.pipeline_runs.error_message` are replaced with a generic
  string rather than the real exception text.

## 26. Change Log

| Date | Version | Author | Description |
|---|---|---|---|

## 27. Ownership

Requires confirmation from the project owner.
