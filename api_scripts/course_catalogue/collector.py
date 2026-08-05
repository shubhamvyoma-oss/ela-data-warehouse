from __future__ import annotations

from typing import Any

from api_scripts.common.edmingle import find_record_list
from api_scripts.common.models import RawRecord, first_value, stable_record_key
from api_scripts.common.repositories import utc_iso
from api_scripts.common.runtime import CollectorRuntime


class CourseCatalogueCollector:
    name = "course_catalogue"

    def run(self, runtime: CollectorRuntime, checkpoint: dict[str, Any]) -> None:
        institute_id = runtime.client.settings.institute_id
        if not institute_id:
            raise ValueError("EDMINGLE_INSTITUTE_ID is required for course_catalogue")
        payload = runtime.client.get_json(
            f"/institute/{institute_id}/courses/catalogue",
            params={"institution_id": institute_id},
            context="course catalogue",
        )
        rows = find_record_list(payload, "course catalogue response")
        records = [_course_record(row, institute_id) for row in rows]
        runtime.commit(
            records,
            {"completed_at": utc_iso(), "record_count": len(records)},
        )


def _course_record(row: dict[str, Any], institute_id: str) -> RawRecord:
    return RawRecord(
        resource="course_catalogue",
        record_key=stable_record_key(
            first_value(row, "bundle_id", "course_id", "id", "bundleId", "courseId"),
            payload=row,
        ),
        payload=row,
        request_context={"institute_id": institute_id},
    )
