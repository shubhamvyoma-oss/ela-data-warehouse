# API Jobs

Each API source has a dedicated folder under `api_scripts/` and exposes a collector through the central runner.

| Job | Source behavior confirmed from supplied scripts | Bronze resource |
| --- | --- | --- |
| `attendance` | Date-windowed report `55`, one request per day | `attendance` |
| `enrollments` | Master-batch index followed by paged class students | `enrollments` |
| `course_catalogue` | Institute course catalogue | `course_catalogue` |
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
