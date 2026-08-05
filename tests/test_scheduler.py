from __future__ import annotations

from pathlib import Path

import pytest

from api_scripts.runner import collector_registry


def _load_schedule():
    import importlib.util

    path = Path("services/scheduler/runner.py")
    spec = importlib.util.spec_from_file_location("warehouse_scheduler", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.load_schedule


def test_example_schedule_only_uses_registered_api_scripts() -> None:
    _, jobs = _load_schedule()(Path("services/scheduler/jobs.example.yaml"))

    assert {job["collector"] for job in jobs} <= set(collector_registry())
    assert all(job["is_enabled"] is False for job in jobs)


def test_schedule_rejects_unknown_collector(tmp_path: Path) -> None:
    path = tmp_path / "jobs.yaml"
    path.write_text(
        "poll_seconds: 30\n"
        "jobs:\n"
        "  - name: bad\n"
        "    collector: imagined\n"
        "    is_enabled: true\n"
        "    interval_minutes: 5\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown collector"):
        _load_schedule()(path)
