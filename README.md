# ELA Data Warehouse

ELA Data Warehouse is the long-term data platform for Vyoma E-Learning Analytics. It collects data from Edmingle APIs, the Edmingle webhook, and approved manual files; preserves immutable raw records; and promotes validated data through Bronze, Silver, and Gold layers.

The platform is intentionally independent of the currently running production webhook. Nothing in the root warehouse deployment replaces, stops, or modifies that service.

## Current milestone

This branch builds the production foundation:

- PostgreSQL `system`, `bronze`, `silver`, and `gold` schemas
- migration tracking and operational metadata
- checkpointed, audited API collection runtime
- dedicated Edmingle API job folders under `api_scripts/`
- validated CSV/XLSX manual imports into Bronze
- containerized migration, scheduler, and operator commands
- deployment preflight checks and operational documentation

Silver transformations and Gold KPI models are added only after their source contracts and business definitions are approved.

## Repository layout

| Path | Responsibility |
| --- | --- |
| `api_scripts/` | Dedicated Edmingle API jobs and their shared collection utilities |
| `services/edmingle_webhook/` | Independently deployed production-compatible webhook service |
| `manual_imports/` | Validated CSV/XLSX ingestion into Bronze |
| `processing/` | Bronze-to-Silver and Silver-to-Gold transformations |
| `platform/` | Scheduling, configuration, monitoring, recovery, and preflight operations |
| `database/` | Warehouse migrations, bootstrap scripts, and verification SQL |
| `shared/` | Runtime code used by multiple platform components |
| `docker/` | Warehouse container assets |
| `documentation/` | Architecture, deployment, operations, and data contracts |
| `tests/` | Platform-level automated tests |

## Local quick start

1. Copy `.env.example` to `.env` and use development-only values.
2. Start the local PostgreSQL profile:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.local.yml up -d postgres
   ```

3. Apply migrations:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.local.yml run --rm warehouse-migrate
   ```

4. Run preflight verification:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.local.yml run --rm warehouse-cli
   ```

Production deployment requires the checklist in `documentation/DEPLOYMENT.md`. Do not commit `.env`, API keys, database passwords, payloads, CSV/XLSX extracts, checkpoints, or logs.

Operator commands are also available through `python warehouse_cli.py`: `migrate`, `preflight`, `collect`, and `import-file`.
