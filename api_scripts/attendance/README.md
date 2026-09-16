# Attendance collector

Ports both halves of the standalone production script `attendance.py` (v1.2.0, "Production-grade
Edmingle report_type=55 attendance pipeline"): the daily fetch loop, and the pandas summary layer
on top of it (per-session and per-batch attendance summaries). Writes into two dedicated Bronze
tables instead of CSV files.

## What changed vs. the previous raw-ingestion version of this job

The previous `AttendanceCollector` fetched `report_type=55` one IST calendar day at a time and
wrote each row, untransformed, into `bronze.edmingle_api_records` via `runtime.commit(...)`. This
version keeps the exact same per-day fetch (`GET /report/csv`, `report_type=55`,
`organization_id`, `start_time`/`end_time` as day-boundary epoch seconds, `response_type=1`), but
adds the original script's business logic on top and writes into two purpose-built tables via
`CollectorRuntime.commit_rows(...)`:

- **`bronze.report55_session_attendance`** -- one row per `(batch_Id, session)`: attendance counts
  and conducted/planned status for that specific class session.
- **`bronze.report55_batch_attendance_summary`** -- one row per batch per requested window:
  aggregate attendance/retention/rating metrics computed across that batch's sessions.

All retry/backoff/circuit-breaker/network-outage-detection logic from the original script is
**not** reimplemented here -- it already lives in `api_scripts.common.api_client.EdmingleApiClient
.get_json()` (per-request retry with exponential backoff + jitter, `Retry-After` handling for 429,
fatal-vs-retriable HTTP status codes) and is shared by every collector in this project. This file
only adds the pandas transform layer.

## Fetch

Same per-day loop and date-window resolution as before, from `ATTENDANCE_START_DATE`,
`ATTENDANCE_END_DATE`, and `ATTENDANCE_LOOKBACK_DAYS` (default lookback: 1 day; range: 1-3650).

**Deviation -- no more checkpoint-driven incremental resume.** The previous version resumed
`start_date` from the checkpoint's `last_completed_date` when no explicit start was given, so a
scheduled run only re-fetched days since the last successful run. This version does **not** do
that. Every summary field below (`session_number`, `first_class_date`, `retention_percentage`,
`attendance_percentage`, ...) depends on a batch's **entire** session history within the window --
fetching only "new" days and computing summaries from just that partial slice would silently
corrupt cumulative counts and first/last-class metrics for any batch with sessions outside that
slice. So this is a **full-window recompute job**: every run resolves its window purely from the
env vars (or the default 1-day lookback) and recomputes both tables' rows from scratch for that
window. This actually matches the *original* script's real behavior more closely than the
previous version did -- the original also never merges a run's summary output with a prior run's;
each invocation's CSV is computed fresh from whatever `--from`/`--to` range was passed to it.

Operators who want a meaningful multi-session summary (rather than a 1-day snapshot) should set
`ATTENDANCE_START_DATE` / `ATTENDANCE_END_DATE`, or a large `ATTENDANCE_LOOKBACK_DAYS`, explicitly.

## Business logic (ported from `attendance.py`)

**Student status filter** (`filter_active_students` / `ATTENDANCE_ACTIVE_STATUS_VALUES`): keeps
only rows whose `studentBatchStatus` (stripped) is in the configured allow-list (default:
`Active`). Uses an allow-list rather than a block-list so any new/unexpected status Edmingle
introduces is excluded by default instead of silently counted.

**Session id column** (`ATTENDANCE_SESSION_ID_COLUMN`, default `attendance_id`): used as the
session key if present in the fetched data, else falls back to `class_Id` with a logged warning --
`class_Id` is a subject/stream identifier, **not** a session, so session counts are undercounted
in that fallback case.

**`clean_data`**: parses `classDate` (`%d %b %Y`) and drops unparseable rows; drops exact duplicate
rows; drops rows missing `batch_Id`, `student_Id`, or the resolved session-id column; logs (without
auto-resolving) any `(student_Id, session)` pair that still has more than one row after dedup;
applies the active-student filter; builds `_class_datetime` from `classDate` + `startTime`
(`%I:%M %p`).

**Present-value sanity guard** (`ATTENDANCE_PRESENT_VALUE`, default `P`): after cleaning, raises if
the configured "present" value never appears anywhere in `studentAttendanceStatus` across the
fetched window -- if it doesn't, every attendance metric below would silently compute to zero.

**`build_class_summary`** (per `batch_Id` + session column) computes, per session:
- `is_conducted` = `classDate <= today` (IST).
- `session_number` = cumulative count per `batch_Id`, ordered by `_class_datetime`, starting at 1.
- `present_count` / `absent_count` / `late_count` = `nunique(student_Id)` where
  `studentAttendanceStatus` equals the present (`ATTENDANCE_PRESENT_VALUE`), absent
  (`ATTENDANCE_ABSENT_VALUE`, default `A`), or late (`ATTENDANCE_LATE_VALUE`, default `L`) value.
- `total_marked` = `nunique(student_Id)` where status is in
  `[present, absent, late, "E", "OL", "NA"]` -- excludes the `"-"` not-marked placeholder.
- `session_attendance_percentage = present_count / total_marked * 100`, rounded to 2 decimals.

  **Deviation:** this port pins `session_attendance_percentage` to **`0`** when `total_marked` is
  `0`, per this porting task's spec. The literal original script instead computes
  `total_marked.replace(0, pd.NA)` before dividing, which yields a **missing** value (not `0`) in
  that edge case. Flag for confirmation if the original's "missing" (NULL in Postgres) semantics
  are actually wanted instead of `0`.

**`compute_batch_summary`** (per `batch_Id`, most aggregates over conducted sessions only):
- `total_students_enrolled` = `nunique(student_Id)` across all fetched rows for the batch.
- `total_present_marks` / `total_absent_marks` = sum of per-session `present_count` /
  `absent_count` across **conducted** sessions (a mark-count, not a unique-student count -- one
  student present in 30 sessions contributes 30).
- `first_class_date` = min `classDate` across **all** sessions; `last_class_date` = max `classDate`
  among **conducted** sessions only.
- `first_class_attendance` = `present_count` of the chronologically first session (from all
  sessions); `last_class_attendance` = `present_count` of the last conducted session (`0` if a
  `last_class_date` exists but that session's attendance is missing).
- `attendance_percentage` = mean(`present_count` across **all** sessions) /
  `total_students_enrolled` * 100, rounded 2dp.
- `average_class_attendance` / `highest_class_attendance` / `lowest_class_attendance` =
  mean / max / min of `present_count` over **conducted** sessions only.
- `average_rating`: `studentRating` coerced numeric; if
  `ATTENDANCE_TREAT_ZERO_RATING_AS_MISSING` (default `true`), a rating of exactly `0` is treated as
  missing before averaging -- `studentRating` is exactly `0` in the overwhelming majority of real
  rows, Edmingle's "not rated" sentinel. Mean per batch, rounded 2dp.
- `retention_percentage = last_class_attendance / first_class_attendance * 100` (±inf -> NULL),
  rounded 2dp; `attendance_drop = first_class_attendance - last_class_attendance`.
- `total_classes_planned` / `total_classes_conducted` / `total_classes_remaining` are computed
  internally (as the original script does) but, matching the original script's own
  `OUTPUT_COLUMNS` (which also excludes them from its CSV), are **not** persisted --
  `bronze.report55_batch_attendance_summary`'s confirmed schema has no columns for them.

## Target tables (confirmed live columns)

`bronze.report55_batch_attendance_summary`:
```
id, pipeline_run_id, batch_id, batch_name, bundle_id, bundle_name, course_id, course_name,
teacher_id, teacher_name, total_students_enrolled, first_class_date, last_class_date,
first_class_attendance, last_class_attendance, total_present_marks, total_absent_marks,
attendance_percentage, average_class_attendance, highest_class_attendance,
lowest_class_attendance, average_rating, retention_percentage, attendance_drop,
summary_window_start, summary_window_end, received_at, created_at
```
`UNIQUE (batch_id, summary_window_start, summary_window_end)`. Since this is a full-window
recompute job, `summary_window_start` / `summary_window_end` are always populated with the actual
date range the run covered, and re-running the *same* window upserts (`ON CONFLICT DO UPDATE`)
rather than duplicating; a different window produces its own row per batch.

`bronze.report55_session_attendance`:
```
id, pipeline_run_id, batch_id, batch_name, course_id, course_name, session_number, session_id,
class_date, is_session_conducted, present_count, absent_count, late_count, total_marked,
session_attendance_percentage, received_at, created_at
```
`UNIQUE (batch_id, session_id)`.

## Storage

Both tables are written via `CollectorRuntime.commit_rows(...)` (`TransformedTableRepository`),
the same mechanism the `students`, `course_enrollments`, and `course_batch_merge` jobs use for
their own dedicated Bronze tables.

- **Session rows** are committed in chunks of `SESSION_COMMIT_CHUNK_SIZE = 2000` rows per
  `commit_rows()` call rather than one insert for the whole window -- a long date range (the
  original script's own docstring cites 546 days / ~150 MB raw output) can produce many thousands
  of `(batch, session)` rows. Chunking bounds each transaction and means a crash partway through
  the write leaves earlier chunks durably committed; a re-run safely re-upserts on
  `(batch_id, session_id)`.
- **Batch summary rows** are committed in a single `commit_rows()` call, since the whole window's
  data must already be in memory to compute the aggregates correctly -- there is no way to compute
  a batch's `retention_percentage` or `first_class_date` from a partial slice.
- If the fetch returns zero rows for the whole window, both tables still get a
  `commit_rows(..., rows=[])` call so the run's checkpoint is recorded.

The checkpoint written after every commit is:
```json
{"summary_window_start": "2026-08-01", "summary_window_end": "2026-08-31", "updated_at": "2026-09-16T12:00:00+00:00"}
```
This is informational only (see "Deviation" above) -- it is not read back to compute the next
run's start date. `checkpoint_partition_key` remains `"daily"`, unchanged from the previous
version of this collector.

## Configuration (env vars)

| Env var | Default | Notes |
|---|---|---|
| `ATTENDANCE_START_DATE` | unset | Explicit window start (`YYYY-MM-DD`). Takes precedence over lookback. |
| `ATTENDANCE_END_DATE` | yesterday (IST) | Explicit window end (`YYYY-MM-DD`). |
| `ATTENDANCE_LOOKBACK_DAYS` | `1` | Used only when `ATTENDANCE_START_DATE` is unset. Must be 1-3650. |
| `ATTENDANCE_ACTIVE_STATUS_VALUES` | `Active` | Comma-separated allow-list for `studentBatchStatus`. New in this port. |
| `ATTENDANCE_SESSION_ID_COLUMN` | `attendance_id` | Falls back to `class_Id` (undercounts sessions) with a logged warning if absent. |
| `ATTENDANCE_PRESENT_VALUE` | `P` | Value of `studentAttendanceStatus` meaning "present". Validated to actually occur in the fetched data. |
| `ATTENDANCE_ABSENT_VALUE` | `A` | Value meaning "absent". |
| `ATTENDANCE_LATE_VALUE` | `L` | Value meaning "late". |
| `ATTENDANCE_TREAT_ZERO_RATING_AS_MISSING` | `true` | Treats `studentRating == 0` as missing rather than a real zero rating before averaging. |

Auth (`apikey`, `ORGID`) and `organization_id` come from `EdmingleSettings.from_environment()`,
shared with every other collector in `api_scripts/`.

## Known gap: not yet wired for a live run

`AttendanceCollector` is already registered in `api_scripts/runner.py`'s `collector_registry()`,
but `run_collector()` constructs `CollectorRuntime` with only `bronze=BronzeRepository(database)`
and no `transformed=TransformedTableRepository(database)`. Calling `commit_rows(...)` (as this
version now does, for both tables) against that runtime raises
`RuntimeError("CollectorRuntime was constructed without a TransformedTableRepository")`. This
mirrors the same gap already called out in `api_scripts/students/README.md` and is left for the
shared wiring step that enables all `commit_rows`-based jobs end-to-end -- out of scope for this
change, which touches only `collector.py` and this README.

## Dependencies

This collector needs `pandas` and `numpy`, matching the other pandas-based ported jobs
(`course_batch_merge`, `course_catalogue_raw`, which already `import pandas` today). Neither
`pandas` nor `numpy` is currently listed in `requirements.txt` (which only has
`psycopg2-binary`, `requests`, `PyYAML`, `openpyxl`) -- both need adding there. Tracked
separately; not modified by this change.
