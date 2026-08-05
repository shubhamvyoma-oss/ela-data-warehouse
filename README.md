# ELA Data Warehouse

ELA Data Warehouse is the long-term data platform for Vyoma E-Learning Analytics. It collects data from Edmingle APIs, the Edmingle webhook, and approved manual files; preserves immutable raw records; and promotes validated data through Bronze, Silver, and Gold layers.

The platform is intentionally independent of the currently running production webhook. Nothing in the root warehouse deployment replaces, stops, or modifies that service.

## Current milestone

This branch builds the production foundation:

- PostgreSQL `system`, `audit`, `monitoring`, `bronze`, `silver`, and `gold` schemas
- migration tracking and operational metadata
- checkpointed, audited API collection runtime
- dedicated Edmingle API job folders under `collectors/`
- validated CSV/XLSX manual imports into Bronze
- containerized migration, scheduler, and operator commands
- deployment preflight checks and operational documentation

Silver transformations and Gold KPI models are added only after their source contracts and business definitions are approved.

## Repository layout

| Path | Responsibility |
| --- | --- |
| `collectors/` | Dedicated Edmingle API jobs and their shared collection utilities |
| `services/` | Independently deployed webhook, scheduler, and future operational services |
| `manual_imports/` | Validated CSV/XLSX ingestion into Bronze |
| `processing/` | Bronze, Silver, Gold, validation, replay, and data-quality processing |
| `warehouse/` | Schema-layer model ownership and contracts |
| `platform/` | Shared platform capabilities such as configuration, alerting, and security |
| `dashboards/` | Reserved backend and frontend boundaries for approved dashboards |
| `database/` | Warehouse migrations, bootstrap scripts, and verification SQL |
| `shared/` | Runtime code used by multiple platform components |
| `docker/` | Warehouse container assets |
| `documentation/` | Architecture, deployment, operations, and data contracts |
| `tests/` | Platform-level automated tests |

## Local quick start

1. Copy `.env.example` to `.env` and use development-only values.
2. Start the local PostgreSQL profile:

   ```bash
   docker compose -f docker-compose.yml -f docker/compose/development.yml up -d postgres
   ```

3. Apply migrations:

   ```bash
   docker compose -f docker-compose.yml -f docker/compose/development.yml run --rm warehouse-migrate
   ```

4. Run preflight verification:

   ```bash
   docker compose -f docker-compose.yml -f docker/compose/development.yml run --rm warehouse-cli
   ```

Production deployment requires the checklist in `documentation/DEPLOYMENT.md`. Do not commit `.env`, API keys, database passwords, payloads, CSV/XLSX extracts, checkpoints, or logs.

Operator commands are also available through `python warehouse_cli.py`: `migrate`, `preflight`, `collect`, and `import-file`.

Repository and PostgreSQL names follow `documentation/NAMING_CONVENTIONS.md`. The evaluation of
the supplied architecture files and its compatibility decisions are recorded in
`documentation/decisions/ADR-001-postgresql-centric-layout-and-naming.md`.
