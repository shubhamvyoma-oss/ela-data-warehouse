# Project Vision

`ela-data-warehouse` is the engineering home for the Vyoma E-Learning Analytics data platform and is intended to become the organization's trusted analytical source.

It is not a webhook repository and it is not a collection of unrelated scripts. The webhook is one ingestion service inside a larger automated platform.

## Supported sources

The current source boundary is deliberately narrow:

- Edmingle LMS webhooks
- Edmingle LMS APIs
- approved manually maintained CSV and Excel files

No future source system is introduced without an explicit requirement.

## Platform flow

```text
Webhook + API jobs + Manual imports
                 |
                 v
             Bronze
                 |
                 v
             Silver
                 |
                 v
              Gold
                 |
                 v
          Power BI / analytics
```

PostgreSQL is the authoritative operational and analytical store. The `system` schema stores
configuration and registries, `audit` stores immutable execution history, and `monitoring` stores
current health state. These operational domains never share business tables with Bronze, Silver,
or Gold. Secret values remain in runtime secret storage rather than PostgreSQL.

## Engineering principles

- automation first
- never lose accepted raw data
- idempotent processing
- replayability and recoverability
- configuration over hardcoding
- audit every important operation
- separate ingestion from transformation
- keep architecture simple and responsibilities explicit

## Deployment boundary

The existing production Edmingle webhook, its port, and `webhook_db.public.webhook_events` remain undisturbed. The warehouse uses a separate PostgreSQL database and separate Docker resources. Migration of production traffic requires separate approval after parallel validation.
