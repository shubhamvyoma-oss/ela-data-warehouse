# Project Standards

## Architecture

- One folder, module, and service has one clear responsibility.
- API jobs live in dedicated folders under `api_scripts/`.
- Shared API mechanics live in `api_scripts/common/`; job-specific request and response logic stays with the job.
- Webhooks and API jobs only ingest. Business transformations do not run in ingestion code.
- Bronze is immutable raw data, Silver is validated and standardized, and Gold is business-ready.
- Operational metadata belongs only in the `system` schema.
- Business consumers read Gold only.
- Configuration is externalized; credentials are never stored in code, config templates, logs, audit details, or database metadata.

## Data reliability

- Every pipeline run receives a stable run identifier and audit trail.
- Collectors update checkpoints only after their Bronze writes commit.
- Replaying the same source data must not create duplicate raw versions.
- Raw payloads must remain available for reprocessing.
- Failed rows are quarantined with non-sensitive failure metadata.
- Schema migrations are ordered, checksummed, transactional, and forward-only in production.

## Repository safety

- Do not commit CSV/XLSX extracts, payloads, runtime checkpoints, logs, dumps, or secrets.
- Do not connect to production unless explicitly authorized.
- Do not deploy automatically.
- Inspect Git status and validate relevant tests before every commit.
- Keep changes small enough to review and document behavior or operational changes.

## Webhook compatibility

Preserve:

- `GET /health` returning `{"status":"running"}`
- `GET /edmingle/webhook` returning `{"status":"ok"}`
- `POST /edmingle/webhook`
- `POST /webhook`
- inserts into `public.webhook_events(source, received_at, raw_payload)`

Never drop, truncate, rename, recreate, or replace `public.webhook_events`.
