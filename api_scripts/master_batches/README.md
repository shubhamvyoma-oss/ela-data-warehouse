# Master batches collector

Collects `GET /short/masterbatch` for all confirmed status values: active (`0`), archived (`1`),
and completed (`3`). Pages use `EDMINGLE_BATCHES_PER_PAGE` and continue according to
`page_context.has_more_page`.

Each nested batch is stored as its untouched raw payload. Bundle, status, class, and master-batch
identifiers are retained as request context so downstream processing can reconstruct the source
relationship without altering Bronze.
