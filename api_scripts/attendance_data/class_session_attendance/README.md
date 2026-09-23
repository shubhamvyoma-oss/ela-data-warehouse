# Class session attendance collector

Direct port of `Attendance data/build_session_attendance.py` (Stage 3 of the legacy Edmingle
attendance pipeline), together with the shared extract functions it imports from
`Attendance data/attendance_crossvalidation.py` -- `fetch_org_attendances`,
`sessions_to_dataframe`, the IST timezone helpers (`to_unix`/`unix_to_ist`), and the
session-status classification (`NOT_CONDUCTED_STATUSES`). It does **not** port
`attendance_crossvalidation.py`'s own standalone spot-check CLI mode (`--class_id` single-class
lookup against `/bundle/general/attendancedet`, cross-validation against report_type=55) --
only the shared functions that script supplies to Stage 3.

Pulls session-wise (not student-wise) attendance for every `class_id` via:

```
GET {EDMINGLE_API_BASE_URL}/organization/attendances
    ?org_id=<org_id>&apikey=<apikey>&start=<unix_ts>&end=<unix_ts>&class_id=<class_id>
```

Edmingle's docs list `apikey`/`orgid` as **headers** for this endpoint (unlike the
report_type=55 endpoint, which is query-param-only) -- the original script sent both headers
and query params to cover whichever the API actually checks. The shared `EdmingleApiClient`
session already attaches `apikey`/`ORGID` headers to every request; org_id/apikey are also sent
as query params here to reproduce that belt-and-braces behavior (a lowercase `orgid` header is
not reproduced separately since HTTP header names are case-insensitive and `ORGID` is already
present -- same reasoning as `class_id_lookup`'s README).

## Dependency: requires `class_id_lookup` to have already run

This job reads its list of `class_id`s (plus `bundle_id`/`bundle_name`) from
**`bronze.class_id_lookup`**, the `class_id_lookup` collector's output table -- not from a CSV,
unlike the original script. **Run `class_id_lookup` first** (which itself depends on
`catalogue`, per that job's own README). If `bronze.class_id_lookup` is empty, this job has
nothing to iterate over and writes zero rows; it does not error.

Concretely, on each run this collector:

1. Opens its own short-lived read-only `Database` connection (separate from the
   `CollectorRuntime`/`TransformedTableRepository` write path) and queries
   `SELECT DISTINCT class_id, bundle_id, bundle_name FROM bronze.class_id_lookup WHERE class_id
   IS NOT NULL`.
2. Skips rows with no resolved `class_id` and deduplicates by `class_id` (keeping the first
   occurrence) -- mirrors the original's
   `lookup_df.dropna(subset=["class_id"]).drop_duplicates(subset=["class_id"])`.
3. Queries `SELECT DISTINCT class_id FROM bronze.class_session_attendance` and skips any
   `class_id` already present -- the output-table-based equivalent of the original's
   CSV-presence-based `load_already_processed()` / resume-on-rerun behavior (same pattern
   `class_id_lookup` uses against its own output table).
4. For each remaining `class_id`, calls `/organization/attendances` for the configured date
   window, shapes the returned sessions, and writes them via
   `CollectorRuntime.commit_rows(...)`, updating the checkpoint
   (`{"class_ids_processed": N, "updated_at": <iso>}`) after every `class_id` -- so a crash or
   rate-limit block loses no already-pulled progress, same as the original's per-class_id CSV
   append. One `CollectorRuntime.commit_rows()` call per `class_id` was chosen over batching
   several `class_id`s per transaction, matching `class_id_lookup`'s convention, since
   `bronze.class_session_attendance`'s `UNIQUE (session_id)` constraint already makes a
   per-class_id commit cheap and crash-safe.
5. A `class_id` whose response has an empty/no sessions is expected and normal (self-paced
   content can have zero attendance-trackable sessions) -- it is still counted as processed via
   the checkpoint, not treated as an error.

## Date window: `CLASS_SESSION_ATTENDANCE_START_DATE` / `_END_DATE` (required)

Unlike the `attendance` (report_type=55) job, which defaults to a rolling lookback window, this
job requires an explicit window -- matching the original CLI's required `--start`/`--end`
arguments, since a bulk historical pull needs an intentional, bounded date range rather than an
implicit "yesterday". Both env vars are `YYYY-MM-DD` and both are required; the collector raises
if either is missing.

## Field mapping and derivations (ported as-is from the shared functions)

- **`to_unix(date_str)`**: parses `YYYY-MM-DD` as IST midnight -> unix timestamp via a manual
  `+5:30` offset (`int(datetime(..., tzinfo=timezone.utc).timestamp() - 5.5*3600)`), no
  `pytz`/`zoneinfo` -- kept exactly as written in both source scripts.
- **`unix_to_ist(ts, fmt)`**: `datetime.fromtimestamp(ts + 5.5*3600, tz=timezone.utc).strftime(fmt)`
  -- same manual-offset style, used for `class_date`, `session_start_ist`, `session_end_ist`.
  Raw UTC unix fields from Edmingle are never written to the table, only their IST-converted
  string counterparts.
- **Session status -> `is_session_conducted`**: `NOT_CONDUCTED_STATUSES = {2, 3}` (Postponed,
  Cancelled); every other Edmingle status code (0 NotSignedIn, 1 SignedIn, 4 LateSignIn,
  5 MissedSignIn, 6 ExcusedAbsent, 7 Absent) counts as conducted. The raw numeric status
  code/label is **not** stored -- only this derived boolean, exactly as in the source.
- **`attendance_pct`**: `round(100 * present / total, 2)` if `total` is truthy, else `NULL`.
- **`session_duration_minutes`**: `round((gmt_end_time - gmt_start_time) / 60, 1)`.
- **`master_batch_name`**: `.strip()`-ed when it is a string (source data often has a leading
  space).
- **`bundle_id`/`bundle_name`**: attached from the `class_id_lookup` row for that `class_id`,
  not from the `/organization/attendances` response -- the original script sourced these two
  fields the same way, from its input lookup file rather than the API payload.
- **`session_id`/`class_id`/`master_batch_id`**: normalized to canonical integer-text strings
  (e.g. `12345.0` -> `"12345"`, matching the original's `Int64` cast intent) for this table's
  text-typed id columns; a row with no `session_id` is skipped (`session_id` is `NOT NULL`),
  same pattern as `course_enrollments` skipping rows with no `class_id`.
- **`session_number`**: rows are sorted chronologically by `session_start_ist` (missing values
  sort last, matching pandas' `sort_values(..., na_position="last")` default), then numbered
  sequentially **per `master_batch_id`** in that order (`df.groupby("master_batch_id")
  .cumcount() + 1`). Every row `/organization/attendances` returns for a `class_id` counts as a
  *planned* session; `is_session_conducted` says whether that planned slot actually happened.

### Difference from `report55_session_attendance`

`bronze.report55_session_attendance` (not yet built as a collector; only its table exists,
migration `006_legacy_pipeline_bronze_tables.sql`) is the per-session detail half of the
separate `attendance` (report_type=55) pipeline, ported from `attendance/attendance.py`. The two
pipelines are independent and intentionally not reconciled against each other in code (that's
what `attendance_crossvalidation.py`'s spot-check CLI mode was for, manually):

- **Different source endpoint**: this job calls `/organization/attendances` (Edmingle's own
  pre-aggregated session totals); `report55_session_attendance` derives its per-session numbers
  by summing student-level P/A/- marks from `report_type=55`.
- **Different `session_number` scope**: this job numbers sessions per `master_batch_id`
  (`UNIQUE (session_id)` on the output table, one row per Edmingle session regardless of which
  `batch_id` context it's viewed from); `bronze.report55_session_attendance` numbers sessions
  per `batch_id` (`UNIQUE (batch_id, session_id)`) -- a broadcast session shared across multiple
  batches gets one `session_number` sequence here, but a separate one per batch there.
- **Different identifying keys**: this table carries `class_id`/`master_batch_id`/`bundle_id`
  (the `/organization/attendances` + `class_id_lookup` join keys); `report55_session_attendance`
  carries `batch_id`/`course_id` (the report_type=55 pipeline's own keys).

## Output table

Writes to `bronze.class_session_attendance` (migration `006_legacy_pipeline_bronze_tables.sql`),
unique on `(session_id)`. Columns: `session_id, class_id, class_name, master_batch_id,
master_batch_name, bundle_id, bundle_name, class_date, total_enrolled_at_session, present_count,
not_marked_count, attendance_pct, taken_by_name, individual_batch_attendance, session_start_ist,
session_end_ist, session_duration_minutes, is_session_conducted, session_number` plus the
standard `id, pipeline_run_id, received_at, created_at` added by `TransformedTableRepository`.
Column mapping from the original `SESSION_BASE_COLUMNS`: `total_enrolled_at_session` -> same,
`present` -> `present_count`, `not_marked` -> `not_marked_count`.

## Rate limiting / retries

The original scripts hand-rolled a ~24-calls/min limiter (`RateLimiter`, from
`pipeline_common.py`) and their own HTTP-429 `"Try after X minutes"` parser
(`parse_retry_after_seconds`). Both are superseded here by the shared `EdmingleApiClient`
(`api_scripts/common/api_client.py`), which already enforces
`EDMINGLE_MIN_REQUEST_INTERVAL_SECONDS` spacing and retries 429/5xx responses with backoff -- no
separate rate limiter is reimplemented in this collector, same simplification `class_id_lookup`
already made.

The application-level `{"code": 200, "classes": [...]}` envelope is not something the generic
client validates (it only rejects Edmingle's own `error_code` 6001/6002), so this collector
explicitly checks `payload.get("code") == 200` before reading `classes` -- a non-200 application
code is logged and treated as "no sessions for this class_id" rather than raised, matching the
original's `if data.get("code") != 200: ... return []` behavior (it does not abort the whole
run over one class_id's bad response).

## Status (updated 2026-09-23)

Registered in `api_scripts/runner.py`'s `collector_registry()` as
`attendance_data.class_session_attendance`, with `TransformedTableRepository` wired into the
`CollectorRuntime` the runner constructs. Runnable via `python warehouse_cli.py collect
attendance_data.class_session_attendance`. It still ships **disabled**
(`system.api_scripts.is_enabled = false` / `system.pipelines.is_enabled = false`, and
`is_enabled: false` in `services/scheduler/jobs.example.yaml`) -- that flag, not registry
wiring, is what gates it from running against the real Edmingle API. This endpoint is metered,
so flipping it on needs a deliberate, credit-aware go-ahead, not just the registry work being
done.
