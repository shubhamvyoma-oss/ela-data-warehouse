# Project Standards

## Architecture Principles

- Keep everything simple.
- Keep everything modular.
- One folder has one responsibility.
- One file has one responsibility.
- One service has one responsibility.
- Prefer descriptive names over short names.
- Avoid unnecessary abstractions.
- Do not redesign working production code during relocation.
- Production compatibility is more important than optimization.
- Build only what is needed now while keeping future growth easy.

## Repository Boundaries

- Service-specific application code, tests, Docker files, migrations, and documentation stay inside the owning service folder.
- Platform-wide documentation belongs in `documentation/`.
- Platform-level Docker assets belong in `docker/`.
- Shared code belongs in `shared/` only when it is genuinely shared.
- Generated files, runtime files, secrets, and local environments are not source assets.

## Webhook Service Standards

The Edmingle webhook service currently defines its own Python, formatting, linting, Docker, and test configuration in `services/edmingle_webhook/`.

Preserve the verified production contract unless a future change is explicitly approved:

- `GET /health`
- `GET /edmingle/webhook`
- `POST /edmingle/webhook`
- `POST /webhook`
- Successful writes to `public.webhook_events(source, received_at, raw_payload)`

Do not change webhook runtime behavior as part of repository foundation work.
