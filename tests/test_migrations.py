from __future__ import annotations

from pathlib import Path


def test_migrations_create_required_schemas_and_contracts() -> None:
    migrations = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(Path("database/migrations").glob("*.sql"))
    )

    for schema in ("system", "audit", "monitoring", "bronze", "silver", "gold"):
        assert f"CREATE SCHEMA IF NOT EXISTS {schema}" in migrations
    assert "audit.pipeline_runs" in migrations
    assert "audit.events" in migrations
    assert "system.collection_checkpoints" in migrations
    assert "system.api_credentials" in migrations
    assert "ALTER TABLE system.collectors RENAME TO api_scripts" in migrations
    assert "system.api_scripts" in migrations
    assert "monitoring.service_health" in migrations
    assert "bronze.edmingle_api_records" in migrations
    assert "bronze.manual_import_rows" in migrations
    # Naive substring match would false-positive on migration 011's own
    # comment explaining *why* it deliberately does not create this table
    # (public.webhook_events is the webhook service's own storage --
    # bronze.webhook_events, a separate table, is what these migrations
    # create instead). Check for the actual CREATE statement, which is the
    # real thing this guard cares about.
    assert "CREATE TABLE public.webhook_events" not in migrations
    assert "CREATE TABLE IF NOT EXISTS public.webhook_events" not in migrations
