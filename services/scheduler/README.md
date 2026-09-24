# Scheduler service

Runs the PostgreSQL-backed job schedule. The service is disabled by default and owns its
runner, health check, and job template. It does not contain job business logic.
