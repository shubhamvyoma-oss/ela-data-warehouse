from __future__ import annotations

from pathlib import Path

from collectors.runner import collector_registry


def test_repository_uses_frozen_component_layout() -> None:
    required = {
        "collectors/attendance",
        "collectors/enrollment",
        "collectors/batches",
        "collectors/catalogue",
        "services/edmingle_webhook",
        "services/scheduler",
        "processing/bronze",
        "processing/silver",
        "processing/gold",
        "warehouse/bronze",
        "warehouse/silver",
        "warehouse/gold",
        "dashboards/backend",
        "dashboards/frontend",
        "docker/compose/development.yml",
    }

    assert all(Path(path).exists() for path in required)
    assert not Path("api_scripts").exists()
    assert not Path("platform/scheduler").exists()


def test_collector_registry_uses_confirmed_names() -> None:
    assert set(collector_registry()) == {"attendance", "enrollment", "batches", "catalogue"}


def test_naming_convention_is_an_explicit_project_standard() -> None:
    standard = Path("documentation/NAMING_CONVENTIONS.md").read_text(encoding="utf-8")

    for prefix in ("vw_", "mv_", "sp_", "fn_"):
        assert f"`{prefix}`" in standard
    assert "public.webhook_events" in standard
