# Naming Conventions

This is the frozen naming authority for the ELA Data Warehouse. It consolidates the supplied
ESD-01.4 convention and resolves conflicts found across the conceptual architecture notes.

## Repository

- Use lowercase `snake_case` for folders, Python modules, and files.
- API collection jobs live under `collectors/<job_name>/`.
- Approved file-ingestion code lives under `manual_imports/`; it is not an API collector.
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

## Confirmed collector names

| Collector | Folder | Bronze resource |
| --- | --- | --- |
| Attendance | `collectors/attendance/` | `attendance_records` |
| Enrollment | `collectors/enrollment/` | `student_enrollments` |
| Batches | `collectors/batches/` | `batches` |
| Catalogue | `collectors/catalogue/` | `courses` |

## Compatibility exceptions

The existing production webhook is an independently deployed service. Its routes,
environment-variable names, internal compatibility tables, and writes to
`public.webhook_events(source, received_at, raw_payload)` are not renamed by repository or
warehouse naming work. Any future migration of that service requires a separate approved,
parallel-validated deployment.
