# Database Bootstrap

The warehouse must use a database separate from `webhook_db`. A PostgreSQL administrator should create the database and least-privilege roles before application migrations run.

Recommended roles:

- `ela_owner`: owns the warehouse database and applies migrations
- `ela_ingest`: writes `bronze` and operational run/checkpoint records
- `ela_transform`: reads Bronze and writes Silver/Gold
- `ela_reporting`: read-only access to Gold
- `ela_monitor`: read-only access to approved `system` operational views

Passwords are created by the administrator or secret manager and never appear in repository SQL. Production role and grant SQL will be finalized against the approved PostgreSQL operating model before deployment.
