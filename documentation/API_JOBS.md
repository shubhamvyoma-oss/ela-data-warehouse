# API Jobs

Each API source has a dedicated folder under `api_scripts/` and exposes a collector through the central runner.

| Job | Source behavior confirmed from supplied scripts | Bronze resource |
| --- | --- | --- |
| `attendance` | Date-windowed report `55`, one request per day | `attendance` |
| `enrollments` | Master-batch index followed by paged class students | `enrollments` |
| `course_catalogue` | Institute course catalogue from the confirmed `response` list | `course_catalogue` |
| `master_batches` | Paged active, archived, and completed master batches | `master_batches` |

Folders for teachers, students, sessions, and transactions are reserved only as documented contracts. Their collectors are not fabricated before endpoint samples are supplied.

## Contract for every collector

1. Read credentials from environment-backed configuration.
2. Read its checkpoint from `system.collector_checkpoints`.
3. Create a `system.pipeline_runs` record.
4. Fetch source pages with bounded retry and rate limiting.
5. Commit immutable Bronze rows and the next checkpoint together.
6. Write business-operation audit events.
7. Mark the run succeeded or failed without logging payloads or secrets.

Legacy CSV outputs, local checkpoint JSON, Windows paths, and embedded credentials are not part of the server implementation.

## Confirmed runtime settings

The supplied enrollment job uses separate batch and student page sizes (both default to 100),
while the attendance job enforces at least 2.5 seconds between calls. These are exposed as
`EDMINGLE_BATCHES_PER_PAGE`, `EDMINGLE_STUDENTS_PER_PAGE`, and
`EDMINGLE_MIN_REQUEST_INTERVAL_SECONDS`. HTTP retries are bounded by
`EDMINGLE_MAX_RETRIES`; HTTP 400/401/403/404 and Edmingle application errors 6001/6002 fail
the run so a bad request can never be checkpointed as an empty successful response.

Attendance reads and writes the `daily` checkpoint partition. The other collectors use the
`default` partition. This distinction is part of the recovery contract.
