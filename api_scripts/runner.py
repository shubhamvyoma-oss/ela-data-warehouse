from __future__ import annotations

import argparse
import logging

from api_scripts.api_key_manager.lifecycle import ApiKeyLifecycle
from api_scripts.common.api_client import EdmingleApiClient
from api_scripts.common.repositories import (
    BronzeRepository,
    CheckpointRepository,
    CredentialMetadataRepository,
    RunRepository,
    TransformedTableRepository,
)
from api_scripts.common.runtime import CollectorRuntime
from shared.config import DatabaseSettings, EdmingleSettings, WarehouseSettings
from shared.database import Database
from shared.logging import configure_logging

LOGGER = logging.getLogger("warehouse.runner")


def collector_registry():
    from api_scripts.attendance.collector import AttendanceCollector
    from api_scripts.attendance_data.catalogue.collector import CourseCatalogueCollector
    from api_scripts.attendance_data.class_id_lookup.collector import ClassIdLookupCollector
    from api_scripts.attendance_data.class_session_attendance.collector import (
        ClassSessionAttendanceCollector,
    )
    from api_scripts.courses_batches.course_batch_merge.collector import CourseBatchMergeCollector
    from api_scripts.courses_batches.course_catalogue_raw.collector import (
        CourseCatalogueRawCollector,
    )
    from api_scripts.ela_mis_datasets.course_enrollments.collector import (
        CourseEnrollmentsCollector,
    )
    from api_scripts.ela_mis_datasets.students.collector import StudentsCollector
    from api_scripts.enrollments_reports.collector import EnrollmentReportsCollector

    return {
        "attendance": AttendanceCollector,
        "attendance_data.catalogue": CourseCatalogueCollector,
        "attendance_data.class_id_lookup": ClassIdLookupCollector,
        "attendance_data.class_session_attendance": ClassSessionAttendanceCollector,
        "courses_batches.course_batch_merge": CourseBatchMergeCollector,
        "courses_batches.course_catalogue_raw": CourseCatalogueRawCollector,
        "ela_mis_datasets.students": StudentsCollector,
        "ela_mis_datasets.course_enrollments": CourseEnrollmentsCollector,
        "enrollment_reports": EnrollmentReportsCollector,
    }


def run_collector(name: str, run_type: str = "manual") -> int:
    registry = collector_registry()
    if name not in registry:
        raise ValueError(f"unknown collector {name!r}; choose from {', '.join(sorted(registry))}")

    warehouse_settings = WarehouseSettings.from_environment()
    configure_logging(warehouse_settings.log_level)
    edmingle_settings = EdmingleSettings.from_environment()
    lifecycle = ApiKeyLifecycle.from_settings(edmingle_settings)
    lifecycle.assert_collection_allowed(
        environment=warehouse_settings.environment
    )
    client = EdmingleApiClient(edmingle_settings)
    collector = registry[name]()
    database = Database(DatabaseSettings.from_environment(), f"ela-collector-{name}")
    checkpoints = CheckpointRepository(database)
    runs = RunRepository(database)
    try:
        CredentialMetadataRepository(database).upsert_edmingle(
            expires_at=lifecycle.expires_at,
            status=lifecycle.status(),
        )
        checkpoint_partition_key = collector.checkpoint_partition_key
        checkpoint_before = checkpoints.get(name, checkpoint_partition_key)
        run_id = runs.start(name, run_type, checkpoint_before)
        runtime = CollectorRuntime(
            collector_name=name,
            run_id=run_id,
            client=client,
            bronze=BronzeRepository(database),
            transformed=TransformedTableRepository(database),
        )
        try:
            collector.run(runtime, checkpoint_before)
            runtime.stats.request_count = client.request_count
            runs.finish(
                run_id,
                name,
                status="succeeded",
                rows_read=runtime.stats.rows_read,
                rows_written=runtime.stats.rows_written,
                rows_rejected=runtime.stats.rows_rejected,
                checkpoint_after=runtime.last_checkpoint or checkpoint_before,
                request_count=client.request_count,
            )
            LOGGER.info(
                "collector succeeded",
                extra={
                    "collector": name,
                    "run_id": str(run_id),
                    "rows_read": runtime.stats.rows_read,
                    "rows_written": runtime.stats.rows_written,
                    "request_count": client.request_count,
                },
            )
            return 0
        except Exception as exc:
            runs.finish(
                run_id,
                name,
                status="failed",
                rows_read=runtime.stats.rows_read,
                rows_written=runtime.stats.rows_written,
                rows_rejected=runtime.stats.rows_rejected,
                checkpoint_after=runtime.last_checkpoint or checkpoint_before,
                request_count=client.request_count,
                error_category=type(exc).__name__,
            )
            LOGGER.error(
                "collector failed",
                extra={
                    "collector": name,
                    "run_id": str(run_id),
                    "error_type": type(exc).__name__,
                },
            )
            return 1
    finally:
        database.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a dedicated ELA API collector")
    parser.add_argument("collector", choices=sorted(collector_registry()))
    parser.add_argument("--run-type", default="manual", choices=("manual", "scheduled", "replay"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return run_collector(args.collector, args.run_type)


if __name__ == "__main__":
    raise SystemExit(main())
