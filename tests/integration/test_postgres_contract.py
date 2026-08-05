from __future__ import annotations

import os
from pathlib import Path

import pytest

from manual_imports.import_file import import_file
from shared.config import DatabaseSettings
from shared.database import Database

pytestmark = pytest.mark.skipif(
    not os.getenv("WAREHOUSE_DB_HOST"),
    reason="requires the isolated PostgreSQL integration environment",
)


def test_manual_import_uses_final_audit_and_bronze_names(tmp_path: Path) -> None:
    source = tmp_path / "naming_contract.csv"
    source.write_text("user_id,name\n1,Asha\n", encoding="utf-8")
    database = Database(DatabaseSettings.from_environment(), "postgres-contract-test")
    try:
        import_id = import_file(
            database,
            source_name="naming_contract",
            path=source,
            required_columns=("user_id", "name"),
        )
        with database.transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT status, rows_loaded FROM audit.manual_imports WHERE id = %s",
                (import_id,),
            )
            assert cursor.fetchone() == ("LOADED", 1)
            cursor.execute(
                """
                SELECT raw_payload
                FROM bronze.manual_import_rows
                WHERE import_id = %s
                """,
                (import_id,),
            )
            assert cursor.fetchone() == ({"user_id": "1", "name": "Asha"},)
            cursor.execute(
                """
                SELECT status
                FROM audit.pipeline_runs
                WHERE pipeline_name = 'manual_import:naming_contract'
                ORDER BY started_at DESC
                LIMIT 1
                """
            )
            assert cursor.fetchone() == ("SUCCESS",)
    finally:
        database.close()
