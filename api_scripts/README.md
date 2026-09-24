# Edmingle API layer

Every confirmed Edmingle API job owns a dedicated folder. API scripts contain only source
collection logic; shared HTTP, retry, checkpoint, Bronze, and audit behavior lives in `common/`.

Folders are grouped by the legacy script folder each job was ported from (see
`documentation/API_JOBS.md` for the full picture and each subfolder's own README for
endpoint/config/table detail):

| Folder | Registered collector name(s) | Bronze table(s) |
| --- | --- | --- |
| `attendance/` | `attendance` | `bronze.report55_batch_attendance_summary`, `bronze.report55_session_attendance` |
| `attendance_data/` | `attendance_data.catalogue`, `attendance_data.class_id_lookup`, `attendance_data.class_session_attendance` | `bronze.course_catalog`, `bronze.class_id_lookup`, `bronze.class_session_attendance` |
| `courses_batches/` | `courses_batches.course_batch_merge`, `courses_batches.course_catalogue_raw` | `bronze.course_batch_merge`, `bronze.course_catalogue_raw` |
| `ela_mis_datasets/` | `ela_mis_datasets.students`, `ela_mis_datasets.course_enrollments` | `bronze.students`, `bronze.course_enrollments` |
| `enrollments_reports/` | `enrollment_reports` | `bronze.enrollment_reports` |
| `api_key_manager/` | not a collector -- `ApiKeyLifecycle` used by every run | `system.api_credentials` (metadata only, never the key value) |
| `edmingle_api_key_generator/` | not a collector -- manual-only `generate.py`, never scheduled | `system.api_credentials` (metadata only) |

Run any registered collector with:

```bash
python warehouse_cli.py collect <name>
```

e.g. `python warehouse_cli.py collect attendance_data.catalogue`. The full registry lives in
`api_scripts/runner.py::collector_registry()` -- that function, not this README, is the source
of truth for exact names if the two ever disagree.

The folders `sessions/`, `teachers/`, and `transactions/` are intentionally reserved. Their
source endpoints were not present in the supplied scripts, so their API jobs will be
implemented only after redacted request and response contracts are provided.

All API scripts store the untouched source record (or, where the project owner explicitly
approved a transform-on-ingest exception for the ported legacy pipelines -- see each folder's
README -- a typed/business-transformed record) in Bronze, attach only request context needed to
understand it, and checkpoint in the same transaction as the Bronze write. They never create CSV
extracts.
