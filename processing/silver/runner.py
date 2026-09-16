from __future__ import annotations

import argparse
import logging

from api_scripts.common.repositories import RunRepository
from shared.config import DatabaseSettings, WarehouseSettings
from shared.database import Database
from shared.logging import configure_logging

LOGGER = logging.getLogger("warehouse.silver")


def transform_registry():
    from processing.silver.class_id_lookup import transform_class_id_lookup
    from processing.silver.enrollment_reports import transform_enrollment_reports
    from processing.silver.students import transform_students

    return {
        "class_id_lookup": transform_class_id_lookup,
        "enrollment_reports": transform_enrollment_reports,
        "students": transform_students,
    }


def run_transform(name: str, run_type: str = "manual") -> int:
    registry = transform_registry()
    if name not in registry:
        raise ValueError(f"unknown transform {name!r}; choose from {', '.join(sorted(registry))}")

    warehouse_settings = WarehouseSettings.from_environment()
    configure_logging(warehouse_settings.log_level)
    pipeline_name = f"silver_{name}"
    database = Database(DatabaseSettings.from_environment(), f"ela-silver-{name}")
    runs = RunRepository(database)
    try:
        run_id = runs.start(pipeline_name, run_type, {})
        try:
            rows_read, rows_written = registry[name](database)
            runs.finish(
                run_id,
                pipeline_name,
                status="succeeded",
                rows_read=rows_read,
                rows_written=rows_written,
                rows_rejected=0,
                checkpoint_after={"rows_read": rows_read, "rows_written": rows_written},
                request_count=0,
            )
            LOGGER.info(
                "transform succeeded",
                extra={"transform": name, "rows_read": rows_read, "rows_written": rows_written},
            )
            return 0
        except Exception as exc:
            runs.finish(
                run_id,
                pipeline_name,
                status="failed",
                rows_read=0,
                rows_written=0,
                rows_rejected=0,
                checkpoint_after={},
                request_count=0,
                error_category=type(exc).__name__,
            )
            LOGGER.error(
                "transform failed",
                extra={"transform": name, "error_type": type(exc).__name__},
            )
            return 1
    finally:
        database.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a Silver-layer transform")
    parser.add_argument("transform", choices=sorted(transform_registry()))
    parser.add_argument("--run-type", default="manual", choices=("manual", "scheduled", "replay"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return run_transform(args.transform, args.run_type)


if __name__ == "__main__":
    raise SystemExit(main())
