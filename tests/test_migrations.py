from __future__ import annotations

from pathlib import Path


def test_migrations_create_required_schemas_and_contracts() -> None:
    migrations = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(Path("database/migrations").glob("*.sql"))
    )

    for schema in ("system", "bronze", "silver", "gold"):
        assert f"CREATE SCHEMA IF NOT EXISTS {schema}" in migrations
    assert "system.pipeline_runs" in migrations
    assert "system.collector_checkpoints" in migrations
    assert "bronze.edmingle_api_records" in migrations
    assert "bronze.manual_import_rows" in migrations
    assert "public.webhook_events" not in migrations
