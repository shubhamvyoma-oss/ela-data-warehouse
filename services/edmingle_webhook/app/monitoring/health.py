from __future__ import annotations

import shutil
from pathlib import Path

from app.config.settings import Settings
from app.database.pool import DatabasePool
from app.queue.file_queue import FileEventQueue


class HealthChecker:
    def __init__(self, settings: Settings, database: DatabasePool, queue: FileEventQueue) -> None:
        self._settings = settings
        self._database = database
        self._queue = queue

    def check(self, include_database: bool) -> dict[str, object]:
        checks: dict[str, object] = {
            "configuration": "ok",
            "filesystem": self._directory_check(self._settings.data_directory),
            "logs": self._directory_check(self._settings.log_directory),
            "queue": self._queue.stats().to_dict(),
            "disk": self._disk_check(self._settings.data_directory),
        }
        if include_database:
            checks["database"] = "ok" if self._database.health_check() else "failed"
        healthy = all(self._is_ok(value) for value in checks.values())
        return {"status": "healthy" if healthy else "unhealthy", "checks": checks}

    def _directory_check(self, path: Path) -> str:
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return "ok"
        except Exception:
            return "failed"

    def _disk_check(self, path: Path) -> dict[str, object]:
        usage = shutil.disk_usage(path)
        free_mb = usage.free // (1024 * 1024)
        return {"status": "ok" if free_mb >= self._settings.disk_min_free_mb else "low", "free_mb": free_mb}

    @staticmethod
    def _is_ok(value: object) -> bool:
        if isinstance(value, str):
            return value == "ok"
        if isinstance(value, dict):
            return value.get("status", "ok") == "ok"
        return True
