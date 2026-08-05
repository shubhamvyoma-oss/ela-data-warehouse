# Scheduler service

Runs the PostgreSQL-backed collector schedule. The service is disabled by default and owns its
runner, health check, and job template. It does not contain collector business logic.
