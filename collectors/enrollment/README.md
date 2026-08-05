# Enrollments collector

Builds the enrollment worklist from every status of `GET /short/masterbatch`, then pages
`GET /masterbatch/classstudents` for each valid class/master-batch pair.

Batch pages use `EDMINGLE_BATCHES_PER_PAGE`; student pages use
`EDMINGLE_STUDENTS_PER_PAGE`. The complete student object is stored unchanged as the enrollment
payload, with its bundle and batch identifiers in request context. Profile-field labels,
attendance totals, and reporting columns are intentionally deferred to Silver transformations.

The checkpoint records the last completed batch, current batch, and next page. A failed page does
not advance state, and a resumed run reuses Bronze idempotency to avoid duplicate versions.
