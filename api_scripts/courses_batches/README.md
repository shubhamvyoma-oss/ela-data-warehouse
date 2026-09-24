# Corses-batches

Groups the 2 jobs ported from the legacy "corses-batches" folder. Both
overlap in domain with `attendance_data.catalogue` (all three build some
form of course/batch catalogue) but are deliberately NOT reconciled into one
table -- each keeps its own source script's exact inclusion rules (e.g.
whether Archived batches are included). See `ROADMAP.md` for the pending
business decision on which source should become the single authoritative
`silver.courses` model.

- `courses_batches.course_batch_merge` -> `bronze.course_batch_merge`
- `courses_batches.course_catalogue_raw` -> `bronze.course_catalogue_raw`

See each subfolder's own README for endpoint/config/table detail. This is
one of six top-level folders under `api_scripts/`, each mapping 1:1 to one
of the original legacy script folders the extract/transform logic was
ported from -- see `documentation/API_JOBS.md` for the full picture.
