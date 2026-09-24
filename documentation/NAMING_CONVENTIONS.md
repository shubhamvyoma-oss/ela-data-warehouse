# Naming Conventions

This is the frozen naming authority for the ELA Data Warehouse. It consolidates the supplied
ESD-01.4 convention and resolves conflicts found across the conceptual architecture notes.

## Repository

- Use lowercase `snake_case` for folders, Python modules, and files.
- API collection jobs live under `api_scripts/<job_name>/`.
- Approved file-ingestion code lives under `manual_imports/`; it is not an API job.
- Independently running processes live under `services/<service_name>/`.
- Shared reusable Python capabilities live under `shared/<capability>/`.
- Processing stages use `processing/bronze/`, `processing/silver/`, `processing/gold/`,
  `processing/validation/`, `processing/replay/`, and `processing/quality/`.
- Warehouse model contracts use `warehouse/bronze/`, `warehouse/silver/`, and `warehouse/gold/`.
- Environment-specific Compose overlays live under `docker/compose/`.

## PostgreSQL

- Schemas are lowercase: `bronze`, `silver`, `gold`, `system`, `audit`, and `monitoring`.
- Tables use lowercase `snake_case` plural nouns. Uncountable state nouns such as
  `service_health` are allowed when the schema makes their purpose unambiguous.
- Views begin `vw_`; materialized views `mv_`; procedures `sp_`; functions `fn_`.
- Mutable tables use `id` as the primary key and preserve meaningful keys with unique constraints.
  `system.schema_migrations` is the sole natural-key exception because its version is immutable.
- Foreign keys use the referenced entity name followed by `_id`.
- Boolean names begin `is_`, `has_`, or `can_`.
- Status values are uppercase and constrained per table.
- Timestamps use descriptive `_at` names and `timestamp with time zone`; runtime values are UTC.
- Bronze source bodies use `raw_payload jsonb`; ingestion preserves the original record first.
- Current configuration/state belongs in `system` and `monitoring`; history belongs in `audit`.
- Credentials tables store lifecycle metadata only. Secret values stay in runtime secret storage.

## Confirmed job names

`api_scripts/` has exactly six top-level folders, one per original legacy
script folder the extract/transform logic was ported from. A folder that
covers more than one job nests each job in its own subfolder with a
`parent.job` registry name; a folder with exactly one job keeps a plain name.

| Job | Folder | Bronze table |
| --- | --- | --- |
| `attendance` | `api_scripts/attendance/` | `report55_batch_attendance_summary`, `report55_session_attendance` |
| `attendance_data.catalogue` | `api_scripts/attendance_data/catalogue/` | `course_catalog` |
| `attendance_data.class_id_lookup` | `api_scripts/attendance_data/class_id_lookup/` | `class_id_lookup` |
| `attendance_data.class_session_attendance` | `api_scripts/attendance_data/class_session_attendance/` | `class_session_attendance` |
| `courses_batches.course_batch_merge` | `api_scripts/courses_batches/course_batch_merge/` | `course_batch_merge` |
| `courses_batches.course_catalogue_raw` | `api_scripts/courses_batches/course_catalogue_raw/` | `course_catalogue_raw` |
| `ela_mis_datasets.students` | `api_scripts/ela_mis_datasets/students/` | `students` |
| `ela_mis_datasets.course_enrollments` | `api_scripts/ela_mis_datasets/course_enrollments/` | `course_enrollments` |
| `enrollment_reports` | `api_scripts/enrollments_reports/` | `enrollment_reports` |

`api_scripts/edmingle_api_key_generator/` (the sixth legacy folder) is not a
Bronze-writing job -- it generates and emails a new Edmingle API key,
see its own README. The pre-existing `api_scripts/api_key_manager/` folder
(key lifecycle/expiry checks) predates this port and isn't one of the six.

The original four raw-ingestion jobs this project started with
(`attendance` -> `attendance_records`, `enrollment` -> `student_enrollments`,
`batches` -> `batches`, `catalogue` -> `courses`, all writing into the single
generic `bronze.edmingle_api_records` table) were replaced or retired when
the six legacy folders were ported -- `attendance` and `catalogue` were
replaced by the richer versions above; `batches` and `enrollment` were
retired (their `system.api_scripts` rows are marked disabled, not deleted,
per the audit-everything rule).

## Compatibility exceptions

The existing production webhook is an independently deployed service. Its routes,
environment-variable names, internal compatibility tables, and writes to
`public.webhook_events(source, received_at, raw_payload)` are not renamed by repository or
warehouse naming work. Any future migration of that service requires a separate approved,
parallel-validated deployment.
