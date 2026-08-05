from __future__ import annotations

import logging
import signal
import time
from pathlib import Path
from typing import Any

import yaml

from api_scripts.runner import collector_registry, run_collector
from shared.config import DatabaseSettings, WarehouseSettings
from shared.database import Database
from shared.logging import configure_logging

LOGGER = logging.getLogger("warehouse.scheduler")
STOP_REQUESTED = False


def _stop(_signum: int, _frame: Any) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True


def load_schedule(path: Path) -> tuple[int, list[dict[str, Any]]]:
    with path.open(encoding="utf-8") as stream:
        payload = yaml.safe_load(stream) or {}
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise ValueError("scheduler config must contain a jobs list")
    poll_seconds = int(payload.get("poll_seconds", 30))
    if poll_seconds < 5 or poll_seconds > 300:
        raise ValueError("poll_seconds must be between 5 and 300")
    available = set(collector_registry())
    seen: set[str] = set()
    jobs: list[dict[str, Any]] = []
    for raw in payload["jobs"]:
        if not isinstance(raw, dict):
            raise ValueError("each scheduler job must be an object")
        name = str(raw.get("name", "")).strip()
        collector = str(raw.get("collector", "")).strip()
        interval = int(raw.get("interval_minutes", 0))
        if not name or name in seen:
            raise ValueError("scheduler job names must be present and unique")
        if collector not in available:
            raise ValueError(f"scheduler job {name!r} uses unknown collector {collector!r}")
        if interval < 1 or interval > 525600:
            raise ValueError(f"scheduler job {name!r} interval is invalid")
        seen.add(name)
        jobs.append(
            {
                "name": name,
                "collector": collector,
                "interval_minutes": interval,
                "is_enabled": bool(raw.get("is_enabled", False)),
            }
        )
    return poll_seconds, jobs


def sync_jobs(database: Database, jobs: list[dict[str, Any]], globally_enabled: bool) -> None:
    with database.transaction() as connection, connection.cursor() as cursor:
        for job in jobs:
            cursor.execute(
                """
                INSERT INTO system.scheduler_jobs (
                    job_name, collector_name, is_enabled, interval_minutes, next_run_at, updated_at
                ) VALUES (%s, %s, %s, %s, now(), now())
                ON CONFLICT (job_name) DO UPDATE
                SET collector_name = EXCLUDED.collector_name,
                    is_enabled = EXCLUDED.is_enabled,
                    interval_minutes = EXCLUDED.interval_minutes,
                    updated_at = now()
                """,
                (
                    job["name"],
                    job["collector"],
                    globally_enabled and job["is_enabled"],
                    job["interval_minutes"],
                ),
            )


def claim_due_job(database: Database) -> tuple[str, str] | None:
    with database.transaction() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            WITH candidate AS (
                SELECT job_name
                FROM system.scheduler_jobs
                WHERE is_enabled = true AND COALESCE(next_run_at, '-infinity') <= now()
                ORDER BY next_run_at NULLS FIRST, job_name
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            UPDATE system.scheduler_jobs AS job
            SET next_run_at = now() + make_interval(mins => job.interval_minutes),
                last_started_at = now(),
                updated_at = now()
            FROM candidate
            WHERE job.job_name = candidate.job_name
            RETURNING job.job_name, job.collector_name
            """
        )
        row = cursor.fetchone()
        return (row[0], row[1]) if row else None


def mark_finished(database: Database, job_name: str, collector_name: str) -> None:
    with database.transaction() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE system.scheduler_jobs
            SET last_run_id = (
                    SELECT id FROM audit.pipeline_runs
                    WHERE pipeline_name = %s
                    ORDER BY started_at DESC LIMIT 1
                ),
                last_finished_at = now(),
                updated_at = now()
            WHERE job_name = %s
            """,
            (collector_name, job_name),
        )


def write_heartbeat(data_directory: Path) -> None:
    data_directory.mkdir(parents=True, exist_ok=True)
    heartbeat = data_directory / "scheduler.heartbeat"
    temporary = data_directory / ".scheduler.heartbeat.tmp"
    temporary.write_text(str(time.time()), encoding="utf-8")
    temporary.replace(heartbeat)


def main() -> int:
    settings = WarehouseSettings.from_environment()
    configure_logging(settings.log_level)
    poll_seconds, jobs = load_schedule(settings.scheduler_config)
    database = Database(DatabaseSettings.from_environment(), "ela-scheduler")
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    try:
        sync_jobs(database, jobs, settings.scheduler_enabled)
        LOGGER.info(
            "scheduler started",
            extra={"globally_enabled": settings.scheduler_enabled, "configured_jobs": len(jobs)},
        )
        while not STOP_REQUESTED:
            write_heartbeat(settings.data_directory)
            claimed = claim_due_job(database) if settings.scheduler_enabled else None
            if claimed:
                job_name, collector_name = claimed
                LOGGER.info(
                    "scheduled collector starting",
                    extra={"job": job_name, "collector": collector_name},
                )
                try:
                    exit_code = run_collector(collector_name, "scheduled")
                except Exception as exc:
                    exit_code = 1
                    LOGGER.error(
                        "scheduled collector could not initialize",
                        extra={
                            "job": job_name,
                            "collector": collector_name,
                            "error_type": type(exc).__name__,
                        },
                    )
                try:
                    mark_finished(database, job_name, collector_name)
                except Exception as exc:
                    LOGGER.error(
                        "scheduler could not persist job completion",
                        extra={
                            "job": job_name,
                            "collector": collector_name,
                            "error_type": type(exc).__name__,
                        },
                    )
                LOGGER.info(
                    "scheduled collector finished",
                    extra={"job": job_name, "collector": collector_name, "exit_code": exit_code},
                )
                continue
            for _ in range(poll_seconds):
                if STOP_REQUESTED:
                    break
                time.sleep(1)
        LOGGER.info("scheduler stopped")
        return 0
    finally:
        database.close()


if __name__ == "__main__":
    raise SystemExit(main())
