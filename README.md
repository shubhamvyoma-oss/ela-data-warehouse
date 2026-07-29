# ELA Data Warehouse

This repository is the long-term engineering home for the Vyoma E-Learning Analytics data platform.

It is a new platform repository, not a migration of the legacy warehouse. The first production-ready component in this repository is the Edmingle webhook receiver under `services/edmingle_webhook/`.

## Current Scope

Phase 1 establishes the repository foundation and places the standalone webhook service in its service boundary.

```text
services/edmingle_webhook/
```

The webhook service keeps its own application code, Docker files, tests, migrations, and service documentation inside that folder.

## Phase 1 Boundaries

`edmingle_webhook` is currently the only implemented service. The remaining top-level directories are intentional platform boundaries for future phases. Empty directories are reserved for future platform components; they are not unfinished implementation work.

## Repository Layout

| Path | Purpose |
| --- | --- |
| `services/` | Production services. Each service owns its runtime code and service-specific documentation. |
| `services/edmingle_webhook/` | Production-compatible Edmingle webhook receiver. |
| `database/` | Future platform database migrations and schema assets. |
| `pipelines/` | Future API collection and transformation pipelines. |
| `shared/` | Future shared code used by more than one service or pipeline. |
| `documentation/` | Platform-wide documentation. |
| `docker/` | Future platform-level Docker assets. |
| `tests/` | Future platform-level tests. Service-specific tests remain with each service. |

## Development

For webhook-specific setup, runtime, Docker, and test instructions, see:

```text
services/edmingle_webhook/README.md
```

Do not commit secrets, production credentials, runtime logs, queue payloads, virtual environments, or generated cache files.
