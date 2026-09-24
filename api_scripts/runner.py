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
from api_scripts.common.runtime import JobRuntime
from shared.config import DatabaseSettings, EdmingleSettings, WarehouseSettings
from shared.database import Database
from shared.logging import configure_logging

LOGGER = logging.getLogger("warehouse.runner")


def job_registry():
    from api_scripts.attendance.attendance import AttendanceJob
    from api_scripts.attendance_data.catalogue.course_catalogue import CourseCatalogueJob
    from api_scripts.attendance_data.class_id_lookup.class_id_lookup import ClassIdLookupJob
    from api_scripts.attendance_data.class_session_attendance.class_session_attendance import (
        ClassSessionAttendanceJob,
    )
    from api_scripts.courses_batches.course_batch_merge.course_batch_merge import CourseBatchMergeJob
    from api_scripts.courses_batches.course_catalogue_raw.course_catalogue_raw import (
        CourseCatalogueRawJob,
    )
    from api_scripts.ela_mis_datasets.course_enrollments.course_enrollments import (
        CourseEnrollmentsJob,
    )
    from api_scripts.ela_mis_datasets.students.students import StudentsJob
    from api_scripts.enrollments_reports.enrollments_reports import EnrollmentReportsJob

    return {
        "attendance": AttendanceJob,
        "attendance_data.catalogue": CourseCatalogueJob,
        "attendance_data.class_id_lookup": ClassIdLookupJob,
        "attendance_data.class_session_attendance": ClassSessionAttendanceJob,
        "courses_batches.course_batch_merge": CourseBatchMergeJob,
        "courses_batches.course_catalogue_raw": CourseCatalogueRawJob,
        "ela_mis_datasets.students": StudentsJob,
        "ela_mis_datasets.course_enrollments": CourseEnrollmentsJob,
        "enrollment_reports": EnrollmentReportsJob,
    }


def run_job(name: str, run_type: str = "manual") -> int:
    registry = job_registry()
    if name not in registry:
        raise ValueError(f"unknown job {name!r}; choose from {', '.join(sorted(registry))}")

    warehouse_settings = WarehouseSettings.from_environment()
    configure_logging(warehouse_settings.log_level)
    edmingle_settings = EdmingleSettings.from_environment()
    lifecycle = ApiKeyLifecycle.from_settings(edmingle_settings)
    lifecycle.assert_collection_allowed(
        environment=warehouse_settings.environment
    )
    client = EdmingleApiClient(edmingle_settings)
    job = registry[name]()
    database = Database(DatabaseSettings.from_environment(), f"ela-job-{name}")
    checkpoints = CheckpointRepository(database)
    runs = RunRepository(database)
    try:
        CredentialMetadataRepository(database).upsert_edmingle(
            expires_at=lifecycle.expires_at,
            status=lifecycle.status(),
        )
        checkpoint_partition_key = job.checkpoint_partition_key
        checkpoint_before = checkpoints.get(name, checkpoint_partition_key)
        run_id = runs.start(name, run_type, checkpoint_before)
        runtime = JobRuntime(
            job_name=name,
            run_id=run_id,
            client=client,
            bronze=BronzeRepository(database),
            transformed=TransformedTableRepository(database),
        )
        try:
            job.run(runtime, checkpoint_before)
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
                "job succeeded",
                extra={
                    "job": name,
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
                "job failed",
                extra={
                    "job": name,
                    "run_id": str(run_id),
                    "error_type": type(exc).__name__,
                },
            )
            return 1
    finally:
        database.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a dedicated ELA API job")
    parser.add_argument("job", choices=sorted(job_registry()))
    parser.add_argument("--run-type", default="manual", choices=("manual", "scheduled", "replay"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return run_job(args.job, args.run_type)


if __name__ == "__main__":
    raise SystemExit(main())
