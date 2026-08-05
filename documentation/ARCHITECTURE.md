# Warehouse Architecture

## Source-of-truth boundaries

ELA Data Warehouse currently accepts only Edmingle webhooks, Edmingle APIs, and approved manual CSV/XLSX files. The running webhook is an independent service and database. Warehouse components never alter the live webhook table.

## Ingestion

`api_scripts/` contains one folder per dedicated API job. Each job owns endpoint-specific parameters, pagination, response extraction, and record identity. `api_scripts/common/` supplies HTTP resilience, rate limiting, audit integration, checkpoint storage, and immutable Bronze writes.

`manual_imports/` validates supported files and stores every accepted source row in Bronze with the file hash and row number.

Ingestion does not apply business transformations.

## Storage

| Schema | Purpose |
| --- | --- |
| `system` | Runs, audit events, checkpoints, schedules, import metadata, and credential expiry metadata |
| `bronze` | Immutable API payloads and manual-import rows |
| `silver` | Typed, deduplicated, standardized business entities after approved contracts exist |
| `gold` | Approved facts, dimensions, KPIs, and reporting models |

Bronze stores payload JSON plus collection context. A content hash and stable record identity make collection replay idempotent while retaining changed versions.

## Runtime

```text
Warehouse scheduler
  |
  +-- attendance job -----------+
  +-- enrollments job ----------+
  +-- course catalogue job -----+--> Bronze --> Silver --> Gold
  +-- master batches job -------+
  +-- future approved jobs -----+

Manual import CLI --------------+

Every component --> system.pipeline_runs + system.audit_events
```

The scheduler starts disabled by default. Operators enable individual jobs only after credentials, endpoint validation, storage capacity, database backup, and dry-run verification succeed.

## Failure rules

- A checkpoint advances only in the same database transaction as its corresponding Bronze write.
- Retriable HTTP failures use bounded exponential backoff and respect `Retry-After`.
- Authentication and contract failures stop the job without advancing the checkpoint.
- Logs and audit details never contain API keys, database passwords, or raw payloads.
- Reprocessing the same payload is safe.
