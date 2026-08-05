from __future__ import annotations

import pytest

from shared.config import ConfigurationError, DatabaseSettings, EdmingleSettings


def _database_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WAREHOUSE_DB_HOST", "localhost")
    monkeypatch.setenv("WAREHOUSE_DB_NAME", "ela_warehouse")
    monkeypatch.setenv("WAREHOUSE_DB_USER", "ela_app")
    monkeypatch.setenv("WAREHOUSE_DB_PASSWORD", "test-only")


def test_database_settings_reject_webhook_database(monkeypatch: pytest.MonkeyPatch) -> None:
    _database_environment(monkeypatch)
    monkeypatch.setenv("WAREHOUSE_DB_NAME", "webhook_db")

    with pytest.raises(ConfigurationError, match="separate"):
        DatabaseSettings.from_environment()


def test_database_settings_build_connection_options(monkeypatch: pytest.MonkeyPatch) -> None:
    _database_environment(monkeypatch)
    settings = DatabaseSettings.from_environment()

    options = settings.connection_kwargs("test")

    assert options["password"] == "test-only"
    assert options["application_name"] == "test"


def test_edmingle_redacted_summary_has_no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EDMINGLE_API_KEY", "private-value")
    monkeypatch.setenv("EDMINGLE_ORGANIZATION_ID", "483")

    summary = EdmingleSettings.from_environment().redacted_summary()

    assert "private-value" not in str(summary)
    assert summary["api_key_configured"] is True
