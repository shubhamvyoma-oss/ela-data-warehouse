# Course catalogue raw collector

Collects the institute catalogue from
`GET /institute/{institute_id}/courses/catalogue?institution_id={institute_id}`.

`EDMINGLE_INSTITUTE_ID` is required (same env var and pattern as the `catalogue`
collector). `EDMINGLE_API_KEY` / `EDMINGLE_ORGANIZATION_ID` (via
`EdmingleSettings.from_environment()`) authenticate the request.

This is a direct, unreconciled port of
`corses-batches/course_catalogue_data (1).py`: a single, unretried GET
(the shared `EdmingleApiClient`'s retry/backoff is used here for safety, but
does not change the request shape), then a generic recursive search for the
first list-of-dicts in the JSON response, flattened with
`pandas.json_normalize()` into whatever columns the response happens to
contain. Only the sink changed: the original script wrote a CSV, this job
writes to `bronze.course_catalogue_raw` (`bundle_id`, `row_sha256` -- a
sha256 of the flattened row's canonical JSON --, `raw_payload` jsonb holding
the full flattened row, unique on `(bundle_id, row_sha256)`).

Full-refresh job: there is no incremental state. Each run re-fetches the
whole catalogue; the checkpoint just records `{"completed_at", "row_count"}`
under partition key `"default"`.

By project decision, this table is deliberately left unreconciled against
the richer `catalogue` and `course_batch_merge` jobs -- three
catalogue-domain tables coexist without reconciliation.
