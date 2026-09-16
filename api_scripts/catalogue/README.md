# Course catalogue collector

Ports the legacy standalone script `build_course_catalog.py` -- the **primary** Stage-1
catalogue builder in the source project (there is a non-primary backup,
`build_course_catalog_alt.py`, which is **not** ported here) -- onto Postgres. It is a
full-refresh job: every run re-fetches the whole catalogue and the Active/Completed
batches and rewrites `bronze.course_catalog` from scratch, exactly like the original
script rewrote its CSV from scratch each run.

This replaces the previous, much simpler version of this collector, which only mirrored
the raw catalogue endpoint into `bronze.edmingle_api_records` with no batch merge or
business logic at all.

## What it does

1. Fetches the institute catalogue: `GET /institute/{institute_id}/courses/catalogue?institution_id={institute_id}`.
2. Fetches batches for **only two** of the three masterbatch statuses -- `0` (Active) and
   `3` (Completed) -- paginated via `GET /short/masterbatch?status={s}&page={n}&per_page=1000&organization_id={org_id}`.
   **Status `1` (Archived) is never fetched.** This is intentional and specific to this
   job's source script; the sibling `course_batch_merge` job fetches all three statuses
   because *its* source script needs the full batch history. Do not add Archived here.
3. Drops rows whose `batch_id` is in a fixed exclusion list (`_BATCH_IDS_TO_EXCLUDE`, 20
   IDs), applied before any other transform. This is an exact-ID exclusion only -- there is
   no keyword-based test/demo filtering in this job (unlike some other catalogue-domain
   jobs).
4. Sums per-bundle enrollment (`bundle_enrollment_count`) and marks the latest batch per
   bundle (`Is_Latest_Batch`) by sorting `[bundle_id, start_date desc (NaN as 0), batch_id
   desc]` and taking the first row of each bundle.
5. Merges the batch rows with the catalogue on `bundle_id` / `Bundle id`, and derives
   `Catalogue_Match`, `Catalogue_Status` (raw mirror), and `Final_Status`:
   - Default `Final_Status = "Completed"` for every row.
   - For the latest batch of a bundle: if the raw catalogue `Status` (stripped) is one of
     `Completed` / `Ongoing` / `Upcoming`, `Final_Status` takes that value; otherwise it is
     blanked out (`""`).
6. Adds one synthetic row per catalogue bundle that has no batch at all (`Has_Batch = 0`,
   `Is_Latest_Batch = 1`, `bundle_enrollment_count = 0`, `Catalogue_Match = 1`), so
   course-only catalogue entries are still represented.
7. Converts `start_date` / `end_date` from Unix epoch seconds to dates.
8. Writes the merged rows into `bronze.course_catalog` via `CollectorRuntime.commit_rows()`
   (`TransformedTableRepository`), upserting on `(batch_id, bundle_id)`.

`EDMINGLE_INSTITUTE_ID` and the standard Edmingle org/API-key settings are required, same
as before.

## Deliberate differences from `course_batch_merge/`

Although this job and `course_batch_merge` share a lot of shape (both merge catalogue +
masterbatch into one row per batch), they are separate, self-contained ports of two
different source scripts and intentionally diverge:

- This job fetches **Active + Completed only**; `course_batch_merge` fetches **all three**
  statuses including Archived. Do not "fix" either one to match the other -- each mirrors
  its own source script exactly.
- This job applies the fixed `_BATCH_IDS_TO_EXCLUDE` ID list; `course_batch_merge` has no
  such list and instead filters by test/demo keyword matching. Neither filter should be
  copied onto the other job.
- Neither job does keyword-based test/demo filtering the same way -- this job does none at
  all.

## Known limitation: synthetic no-batch rows won't upsert cleanly

`bronze.course_catalog` has a `UNIQUE (batch_id, bundle_id)` constraint, and this collector
upserts on it via `ON CONFLICT`. Synthetic "catalogue-only, no batch" rows always have
`batch_id = NULL`. Postgres never treats two `NULL`s as equal for uniqueness purposes, so
those specific rows will **not** upsert across repeated full-refresh runs -- each run
inserts a fresh row for every catalogue bundle that still has no batches, rather than
updating the previous run's row in place. This is the same known limitation already
documented in the `course_batch_merge` README, inherited from the pre-existing table
definition (which this change does not modify) rather than from collector logic; flagging
it here for whoever owns downstream Silver/Gold modeling of this table.

## Ships disabled

Adding `pandas`/`numpy` to `requirements.txt` (this module imports `pandas`) is left for
whoever centrally manages that file -- not done as part of this change. This collector
should not be run against the live Edmingle API until that dependency and any collector
registry / `TransformedTableRepository` wiring needed to invoke it are confirmed in place.
