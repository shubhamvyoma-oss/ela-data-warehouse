# Compose environments

`development.yml` is the local PostgreSQL overlay used with the root `docker-compose.yml` base.
Staging and production overlays will be added only when their server resources and secret delivery
contracts are approved; empty or speculative deployment files are intentionally not created.
