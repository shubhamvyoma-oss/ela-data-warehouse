# Course/batch merge collector

Ports the legacy standalone script `Course_Batch_Merge.py` (previously run by hand and
written to a CSV) onto Postgres. It is a full-refresh job: every run re-fetches the whole
catalogue and all batches and rewrites `bronze.course_batch_merge` from scratch, exactly
like the original script rewrote its CSV from scratch each run.

## What it does

1. Fetches the institute catalogue: `GET /institute/{institute_id}/courses/catalogue?institution_id={institute_id}`.
2. Fetches **all batches across all three statuses** -- `0` (Active), `1` (Archived), and
   `3` (Completed) -- paginated via `GET /short/masterbatch?status={s}&page={n}&per_page=1000&organization_id={org_id}`.
   Unlike `api_scripts/batches` (`MasterBatchCollector`), Archived is **not** skipped here:
   the source script's business logic needs the full course/batch history to compute
   `Is_Latest_Batch` and `Final_Status` correctly.
3. Filters out test batches (`batch_name` containing "test batch") and test/junk courses
   (no catalogue match **and** `bundle_name` containing test/demo/dummy/sample/etc.).
4. Marks the latest batch per bundle (`Is_Latest_Batch`), sums per-bundle enrollment
   (`bundle_enrollment_count`), and derives `Final_Status` / `Catalogue_Status` from the
   raw catalogue `Status` field.
5. Adds one synthetic row per catalogue bundle that has no batch at all
   (`Has_Batch = 0`), so course-only catalogue entries are still represented.
6. Writes the merged rows into `bronze.course_batch_merge` via
   `CollectorRuntime.commit_rows()` (`TransformedTableRepository`), upserting on
   `(batch_id, bundle_id)`.

`EDMINGLE_INSTITUTE_ID` and the standard Edmingle org/API-key settings are required, same
as `catalogue/`.

## Deliberate differences from `catalogue/` and `batches/`

This job is **not** a reconciliation of `catalogue/` and `batches/` -- it is a separate,
self-contained port of the original script's own extract+transform logic, and intentionally
does not share row-level business rules with either of those collectors:

- It replaces the *role* that the old `batches/` (`MasterBatchCollector`) job used to play
  for downstream batch reporting -- per project decision, batch/catalogue merge reporting
  now comes from this job's output table instead of the raw `bronze.edmingle_api_records`
  mirror that `batches/` writes.
- It fetches Archived batches (`status=1`); some other jobs in this codebase intentionally
  skip Archived for their own purposes. Keeping Archived here is intentional and required
  by the source script's `Is_Latest_Batch` logic across the full batch history.
- There is **no** batch-id exclusion list here (unlike `catalogue/`-adjacent jobs that
  filter specific known-bad batch IDs). Only the generic test/demo/junk keyword filters
  from the original script apply.
- `catalogue_raw_status` is a straight mirror of the catalogue API's raw `Status` field;
  `catalogue_status` and `final_status` are the derived business fields. All three are kept
  because the source script keeps both the raw and derived views side by side.

## Known limitation inherited from the table schema

`bronze.course_batch_merge` has a `UNIQUE (batch_id, bundle_id)` constraint, and this
collector upserts on it via `ON CONFLICT`. Synthetic "catalogue-only, no batch" rows always
have `batch_id = NULL`. Postgres never treats two `NULL`s as equal for uniqueness purposes,
so those specific rows will **not** upsert across repeated full-refresh runs -- each run
inserts a fresh row for every catalogue bundle that still has no batches, rather than
updating the previous run's row in place. This is a property of the pre-existing table
definition (which this change does not modify), not of the collector logic; flagging it
here for whoever owns downstream Silver/Gold modeling of this table.

## Ships disabled

This collector is **not** registered in `api_scripts/runner.py`'s `collector_registry()`,
and `run_collector()` there does not yet pass a `TransformedTableRepository` into
`CollectorRuntime` (it only wires up `bronze=BronzeRepository(...)`, not
`transformed=...`). Wiring both of those up is required before this job can actually be
invoked via the CLI (`warehouse_cli.py collect course_batch_merge` today would fail with
"unknown collector"). That wiring, and adding `pandas`/`numpy` to `requirements.txt`
(this module imports `pandas`), are left for whoever enables this job for real -- this
change intentionally ships as inert, uncalled code so it does not run against the live
Edmingle API or spend credits.
