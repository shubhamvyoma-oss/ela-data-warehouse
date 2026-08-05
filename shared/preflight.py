from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from collectors.api_key_manager.lifecycle import ApiKeyLifecycle
from shared.config import DatabaseSettings, EdmingleSettings, WarehouseSettings
from shared.database import Database


def run_preflight(*, require_api: bool = False) -> dict[str, Any]:
    warehouse = WarehouseSettings.from_environment()
    database_settings = DatabaseSettings.from_environment()
    checks: list[dict[str, Any]] = []

    data_path = _existing_parent(warehouse.data_directory)
    free_mb = shutil.disk_usage(data_path).free // (1024 * 1024)
    checks.append(
        {
            "name": "disk_space",
            "status": "pass" if free_mb >= warehouse.minimum_free_disk_mb else "fail",
            "free_mb": free_mb,
            "required_mb": warehouse.minimum_free_disk_mb,
        }
    )

    database = Database(database_settings, "ela-preflight")
    try:
        database_ok = database.health_check()
        checks.append({"name": "database_connection", "status": "pass" if database_ok else "fail"})
        if database_ok:
            with database.transaction() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT schema_name
                    FROM information_schema.schemata
                    WHERE schema_name IN (
                        'system', 'audit', 'monitoring', 'bronze', 'silver', 'gold'
                    )
                    """
                )
                schemas = {row[0] for row in cursor.fetchall()}
            required_schemas = {"system", "audit", "monitoring", "bronze", "silver", "gold"}
            missing = sorted(required_schemas - schemas)
            checks.append(
                {
                    "name": "warehouse_schemas",
                    "status": "pass" if not missing else "fail",
                    "missing": missing,
                }
            )
    finally:
        database.close()

    if require_api or warehouse.scheduler_enabled:
        api = EdmingleSettings.from_environment()
        lifecycle = ApiKeyLifecycle.from_settings(api)
        lifecycle_status = lifecycle.status()
        api_status = (
            "fail" if lifecycle_status in {"unknown", "stop_window", "expired"} else "pass"
        )
        checks.append(
            {
                "name": "edmingle_configuration",
                "status": api_status,
                "api_key_lifecycle_status": lifecycle_status,
                "configuration": api.redacted_summary(),
            }
        )

    status = "pass" if all(check["status"] == "pass" for check in checks) else "fail"
    return {"status": status, "environment": warehouse.environment, "checks": checks}


def _existing_parent(path: Path) -> Path:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate
