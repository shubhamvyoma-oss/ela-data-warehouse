# Warehouse Architecture

## Source-of-truth boundaries

ELA Data Warehouse currently accepts only Edmingle webhooks, Edmingle APIs, and approved manual CSV/XLSX files. The running webhook is an independent service and database. Warehouse components never alter the live webhook table.

## Ingestion

`collectors/` contains one folder per dedicated API job. Each job owns endpoint-specific parameters, pagination, response extraction, and record identity. `collectors/common/` supplies HTTP resilience, rate limiting, audit integration, checkpoint storage, and immutable Bronze writes.

`manual_imports/` validates supported files and stores every accepted source row in Bronze with the file hash and row number.

Ingestion does not apply business transformations.

## Storage

| Schema | Purpose |
| --- | --- |
| `system` | Configuration, registries, checkpoints, schedules, locks, and non-secret credential metadata |
| `audit` | Immutable pipeline, event, and manual-import history |
| `monitoring` | Current service, collector, and database health state |
| `bronze` | Immutable API payloads and manual-import rows |
| `silver` | Typed, deduplicated, standardized business entities after approved contracts exist |
| `gold` | Approved facts, dimensions, KPIs, and reporting models |

Bronze stores payload JSON plus collection context. A content hash and stable record identity make collection replay idempotent while retaining changed versions.

## Runtime

```text
Warehouse scheduler
  |
  +-- attendance job -----------+
  +-- enrollment job -----------+
  +-- catalogue job ------------+--> Bronze --> Silver --> Gold
  +-- batches job --------------+
  +-- future approved jobs -----+

Manual import CLI --------------+

Every component --> audit.pipeline_runs + audit.events
```

The scheduler starts disabled by default. Operators enable individual jobs only after credentials, endpoint validation, storage capacity, database backup, and dry-run verification succeed.

## Failure rules

- A checkpoint advances only in the same database transaction as its corresponding Bronze write.
- Retriable HTTP failures use bounded exponential backoff and respect `Retry-After`.
- Authentication and contract failures stop the job without advancing the checkpoint.
- Logs and audit details never contain API keys, database passwords, or raw payloads.
- Reprocessing the same payload is safe.
