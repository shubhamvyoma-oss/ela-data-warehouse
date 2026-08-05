# ADR-001: PostgreSQL-centric layout and naming

- Status: Accepted
- Date: 2026-08-06

## Context

The supplied architecture files propose a PostgreSQL-centric data platform, six warehouse
schemas, dedicated api_script and services, and a durable naming convention. The existing
repository already implements the core Bronze runtime but used an older `api_scripts/` layout and
stored historical audit data inside `system`.

The source files are conceptual and contain conflicts. Examples include `collector_registry`
versus `api_script`, singular raw-table examples versus the plural-table rule, and both encrypted
database credentials and environment-backed secrets.

## Decision

Adopt the stable principles:

- keep the business project and repository name ELA Data Warehouse;
- use `api_script/`, `services/`, `processing/`, `warehouse/`, `platform/`, `dashboards/`,
  `manual_imports/`, `database/`, `docker/`, `shared/`, `documentation/`, and `tests/` as ownership
  boundaries;
- use PostgreSQL schemas `bronze`, `silver`, `gold`, `system`, `audit`, and `monitoring`;
- keep current configuration/state in `system`/`monitoring` and append-only history in `audit`;
- follow `documentation/NAMING_CONVENTIONS.md` when conceptual examples disagree;
- keep secret values in runtime secret storage and only lifecycle metadata in PostgreSQL;
- apply database changes through a forward-only migration rather than rewriting applied history.

## Compatibility boundary

The running Edmingle webhook remains an independent service. Its routes, container behavior, and
`webhook_db.public.webhook_events` table are unchanged. This is an intentional exception to the
new warehouse layout until a separately approved production migration exists.

## Deferred concepts

The monitoring, notification, dashboard, student, teacher, session, and transaction components
remain documented boundaries only. Implementations are deferred until endpoint, behavior,
security, and ownership contracts are supplied. Automated API-key generation is also deferred
until its endpoint and redacted response contract are available.

## Consequences

Imports, Docker packaging, scheduler paths, operator documentation, tests, and SQL references use
the new names. Migration `003_naming_and_platform_schemas.sql` upgrades existing warehouse
databases; migration `004_platform_registry_seeds.sql` registers the approved platform components.
The same ordered migrations produce the final schema on a fresh installation.
