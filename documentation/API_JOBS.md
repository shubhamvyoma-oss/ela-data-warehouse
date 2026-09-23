# API Jobs

Each API source has a dedicated folder under `api_scripts/` and exposes a collector through the central runner. Registered collector names below are exactly what `python warehouse_cli.py collect <name>` expects, matching `api_scripts/runner.py::collector_registry()`.

| Registered collector | Folder | Source behavior | Bronze table |
| --- | --- | --- | --- |
| `attendance` | `attendance/` | Date-windowed report `55`, one request per day | `report55_batch_attendance_summary`, `report55_session_attendance` |
| `attendance_data.catalogue` | `attendance_data/catalogue/` | Institute course catalogue, merge/exclusion/latest-batch logic | `course_catalog` |
| `attendance_data.class_id_lookup` | `attendance_data/class_id_lookup/` | Resolves `class_id`(s) per batch (reads `course_catalog`) | `class_id_lookup` |
| `attendance_data.class_session_attendance` | `attendance_data/class_session_attendance/` | Per-session attendance per `class_id` (reads `class_id_lookup`) | `class_session_attendance` |
| `corses_batches.course_batch_merge` | `corses_batches/course_batch_merge/` | Paged active, archived, and completed master batches | `course_batch_merge` |
| `corses_batches.course_catalogue_raw` | `corses_batches/course_catalogue_raw/` | Flattened catalogue endpoint, dynamic columns | `course_catalogue_raw` |
| `ela_mis_datasets.students` | `ela_mis_datasets/students/` | Paged class students, one row per student | `students` |
| `ela_mis_datasets.course_enrollments` | `ela_mis_datasets/course_enrollments/` | Per-(student, class) attendance summary (reads `students` for eligible user_ids) | `course_enrollments` |
| `enrollment_reports` | `enrollments_reports/` | Date-chunked row-level enrollment report | `enrollment_reports` |

Not a scheduled collector: `edmingle_api_key_generator/generate.py` is a manual-only script
(username/password login, not API-key-authenticated) that generates a new Edmingle tutor API
key, emails it to the configured recipients, and records only lifecycle metadata
(`expires_at`/`status`) -- never the key value itself -- via the same `system.api_credentials`
table every collector's `ApiKeyLifecycle` check reads. See `api_scripts/api_key_manager/README.md`
and `edmingle_api_key_generator/generate.py`'s own docstring for the "never log/store the key"
constraint.

Folders for teachers, sessions, and transactions are reserved only as documented contracts.
Their API scripts are not fabricated before endpoint samples are supplied.

## Contract for every collector

1. Read credentials from environment-backed configuration.
2. Read its checkpoint from `system.collection_checkpoints`.
3. Create an `audit.pipeline_runs` record.
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

Attendance reads and writes the `daily` checkpoint partition. The other API scripts use the
`default` partition. This distinction is part of the recovery contract.
