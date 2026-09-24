# Class-id lookup job

Direct 1:1 port of `Attendance data/resolve_class_ids.py` (Stage 2 of the legacy Edmingle
attendance pipeline). Resolves the hidden per-subject `class_id`(s) for every batch via

```
GET {EDMINGLE_API_BASE_URL}/masterbatch/{batch_id}
```

sending `apikey`/`org_id` as query params in addition to the `apikey`/`ORGID` headers the
shared `EdmingleApiClient` session already attaches to every request (the original script sent
apikey/org id in both the headers and the query string; a lowercase `orgid` header the original
also sent is not reproduced separately since HTTP header names are case-insensitive and `ORGID`
is already present).

## Dependency: requires `catalogue` to have already run

This job reads its list of batches from **`bronze.course_catalog`**, which is populated by the
`catalogue` job (the port of `Attendance data/build_course_catalog.py`, Stage 1 of the
legacy pipeline) -- not from a CSV, unlike the original script. **Run `catalogue` first.** If
`bronze.course_catalog` is empty, this job simply has nothing to iterate over and writes zero
rows; it does not error.

Concretely, on each run this job:

1. Opens its own short-lived read-only `Database` connection (separate from the
   `JobRuntime`/`TransformedTableRepository` write path) and queries
   `SELECT DISTINCT batch_id, bundle_id, bundle_name, batch_name FROM bronze.course_catalog
   WHERE batch_id IS NOT NULL`.
2. Deduplicates by `batch_id`, keeping the first occurrence -- matching the original script's
   `catalog_df.dropna(subset=["batch_id"]).drop_duplicates(subset=["batch_id"])`.
3. Queries `SELECT DISTINCT batch_id FROM bronze.class_id_lookup` and skips any batch already
   present -- the output-table-based equivalent of the original's CSV-presence-based
   `load_already_processed()` / resume-on-rerun behavior.
4. For each remaining batch, calls `/masterbatch/{batch_id}` and writes the resolved row(s)
   immediately via `JobRuntime.commit_rows(...)`, updating the checkpoint
   (`{"batches_processed": N, "updated_at": <iso>}`) after every batch -- so a crash or
   rate-limit block loses no already-resolved progress, same as the original's per-batch CSV
   append.

## Response shape (confirmed live, contradicts Edmingle's own docs)

```json
{
  "code": 200,
  "class": {
    "courses_array": [ { "class_id": 123, "tutor_name": "...", "...": "..." } ],
    "class_id": 999
  }
}
```

The top-level `class.class_id` is actually the **batch** id, misleadingly named. The real
per-subject `class_id`s -- the ones attendance is actually queried against -- are nested inside
`class.courses_array[]`. A batch can resolve to zero, one, or multiple `class_id`s:

- **Zero** (`courses_array` empty/missing): one row is still written with `class_id = NULL` and
  the other resolved fields `NULL`, so the batch is never silently dropped.
- **Multiple**: each item in `courses_array` becomes its own row, all sharing the same
  `batch_id`/`bundle_id`/`bundle_name`/`batch_name`.

For each `courses_array` item, `class_id`, `tutor_name`, `tutor_id`, `total_classes`,
`completed_classes` (source key `completed`), `cancelled_classes` (source key `cancelled`), and
`num_users` are copied straight across; `associated_masterbatches` (a list in the API response)
is joined with commas into a single string, exactly as the original CSV version did.

## Output table

Writes to `bronze.class_id_lookup` (migration `006_legacy_pipeline_bronze_tables.sql`), unique
on `(batch_id, class_id)`. Columns: `bundle_id, bundle_name, batch_id, batch_name, class_id,
tutor_name, tutor_id, total_classes, completed_classes, cancelled_classes, num_users,
associated_masterbatches` plus the standard `id, pipeline_run_id, received_at, created_at`
added by `TransformedTableRepository`.

## Rate limiting / retries

The original script hand-rolled a ~24-calls/min limiter and its own HTTP-429
`"Try after X minutes"` parser. Both are superseded here by the shared `EdmingleApiClient`
(`api_scripts/common/api_client.py`), which already enforces
`EDMINGLE_MIN_REQUEST_INTERVAL_SECONDS` spacing and retries 429/5xx responses with backoff --
no separate rate limiter is reimplemented in this job.

## Status (updated 2026-09-23)

Registered in `api_scripts/runner.py`'s `job_registry()` as
`attendance_data.class_id_lookup`, with `TransformedTableRepository` wired into the
`JobRuntime` the runner constructs. Runnable via `python warehouse_cli.py collect
attendance_data.class_id_lookup`. It still ships **disabled**
(`system.api_scripts.is_enabled = false` / `system.pipelines.is_enabled = false`, and
`is_enabled: false` in `services/scheduler/jobs.example.yaml`) -- that flag, not registry
wiring, is what gates it from running against the live Edmingle API.
