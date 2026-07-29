# AGENTS.md

Instructions for AI agents and developers working in `ela-data-warehouse`.

## Project Identity

This is a new long-term data platform repository. It is not a migration of the legacy warehouse and it is not only a webhook project.

The first production-ready service is:

```text
services/edmingle_webhook/
```

## Required Reading

Before making non-trivial changes, read:

1. `PROJECT_VISION.md`
2. `PROJECT_STANDARDS.md`
3. `README.md`
4. The relevant service README and docs.

For webhook work, read:

```text
services/edmingle_webhook/README.md
services/edmingle_webhook/docs/
```

## Safety Rules

- Do not connect to production unless explicitly authorized.
- Do not use or commit production credentials.
- Do not deploy automatically.
- Do not change production webhook behavior without explicit approval.
- Do not redesign working production code during relocation or repository-structure work.
- Do not migrate legacy warehouse code unless explicitly requested.
- Do not commit runtime logs, queue payloads, virtual environments, caches, or temporary files.

## Webhook Compatibility Rules

The webhook service must preserve:

- `GET /health` returning `{"status":"running"}`
- `GET /edmingle/webhook` returning `{"status":"ok"}`
- `POST /edmingle/webhook` as the primary receiver
- `POST /webhook` as the compatibility alias
- Inserts into `public.webhook_events(source, received_at, raw_payload)`

Do not drop, truncate, rename, recreate, or replace `public.webhook_events`.

## Development Rules

- Inspect Git status before making changes.
- Keep changes small and focused.
- Keep service-specific assets inside the owning service.
- Add shared abstractions only when more than one component needs them.
- Update documentation when behavior, structure, deployment, or operations change.
- Run relevant verification before reporting completion.
