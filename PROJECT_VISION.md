# Project Vision

`ela-data-warehouse` is the long-term engineering platform for the Vyoma E-Learning Analytics data system.

This repository is not a migration of the legacy warehouse and is not only a webhook project. It will gradually become the single home for production services, API collection pipelines, Bronze/Silver/Gold transformations, database migrations, scheduling, monitoring, notifications, verification, reporting, and durable documentation.

## Phase 1

The first phase establishes the repository foundation and places the existing production-ready webhook service at:

```text
services/edmingle_webhook/
```

The webhook service remains a standalone service. Its internal structure and behavior are preserved.

## Long-Term Direction

Future functionality should be added only when needed and should fit naturally into the repository boundaries:

- Services live under `services/`.
- Data collection and transformation workflows live under `pipelines/`.
- Platform database assets live under `database/`.
- Shared code is introduced under `shared/` only after more than one component needs it.
- Platform-wide documentation lives under `documentation/`.

Do not build future phases before they are required.
