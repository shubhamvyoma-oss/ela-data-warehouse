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
    assert "system.collectors" in migrations
    assert "monitoring.service_health" in migrations
    assert "bronze.edmingle_api_records" in migrations
    assert "bronze.manual_import_rows" in migrations
    assert "public.webhook_events" not in migrations
