from __future__ import annotations

from typing import Any

from api_scripts.common.edmingle import (
    BATCH_STATUSES,
    flatten_master_batches,
    has_more_pages,
    require_record_list,
)
from api_scripts.common.models import RawRecord, first_value, stable_record_key
from api_scripts.common.repositories import utc_iso
from api_scripts.common.runtime import CollectorRuntime


class EnrollmentCollector:
    name = "enrollments"
    checkpoint_partition_key = "default"

    def run(self, runtime: CollectorRuntime, checkpoint: dict[str, Any]) -> None:
        batches = sorted(_fetch_batch_index(runtime), key=_batch_sort_key)
        in_progress = bool(checkpoint.get("in_progress"))
        last_completed = str(checkpoint.get("last_completed_batch_key", "")) if in_progress else ""
        current_batch = str(checkpoint.get("current_batch_key", "")) if in_progress else ""
        resume_page = int(checkpoint.get("next_page", 1)) if in_progress else 1

        for batch in batches:
            batch_key = _batch_sort_key(batch)
            if last_completed and batch_key <= last_completed:
                continue
            if current_batch and batch_key < current_batch:
                continue
            page = resume_page if current_batch == batch_key else 1
            while True:
                payload = runtime.client.get_json(
                    "/masterbatch/classstudents",
                    params={
                        "class_id": batch["class_id"],
                        "master_batch_id": batch["master_batch_id"],
                        "page": page,
                        "per_page": runtime.client.settings.students_per_page,
                        "ORGID": runtime.client.settings.organization_id,
                    },
                    context=f"enrollments batch={batch_key} page={page}",
                )
                students = require_record_list(payload, "students", "classstudents response")
                records = [_enrollment_record(student, batch) for student in students]
                more = has_more_pages(payload)
                next_checkpoint: dict[str, Any]
                if more:
                    next_checkpoint = {
                        "in_progress": True,
                        "last_completed_batch_key": last_completed,
                        "current_batch_key": batch_key,
                        "next_page": page + 1,
                        "updated_at": utc_iso(),
                    }
                else:
                    last_completed = batch_key
                    next_checkpoint = {
                        "in_progress": True,
                        "last_completed_batch_key": batch_key,
                        "current_batch_key": "",
                        "next_page": 1,
                        "updated_at": utc_iso(),
                    }
                runtime.commit(records, next_checkpoint)
                if not more:
                    break
                page += 1

        runtime.commit(
            [],
            {
                "in_progress": False,
                "completed_at": utc_iso(),
                "last_completed_batch_key": "",
                "current_batch_key": "",
                "next_page": 1,
            },
        )


def _fetch_batch_index(runtime: CollectorRuntime) -> list[dict[str, Any]]:
    batches: list[dict[str, Any]] = []
    for status in BATCH_STATUSES:
        page = 1
        while True:
            payload = runtime.client.get_json(
                "/short/masterbatch",
                params={
                    "status": status,
                    "page": page,
                    "per_page": runtime.client.settings.batches_per_page,
                    "organization_id": runtime.client.settings.organization_id,
                },
                context=f"enrollment batch index status={status} page={page}",
            )
            courses = require_record_list(payload, "courses", "master batch response")
            for _batch, context, _key in flatten_master_batches(courses, status):
                if context.get("class_id") and context.get("master_batch_id"):
                    batches.append(context)
            if not has_more_pages(payload):
                break
            page += 1
    unique = {_batch_sort_key(batch): batch for batch in batches}
    return list(unique.values())


def _batch_sort_key(batch: dict[str, Any]) -> str:
    return stable_record_key(
        batch.get("bundle_id"),
        batch.get("master_batch_id"),
        batch.get("class_id"),
        payload=batch,
    )


def _enrollment_record(student: dict[str, Any], batch: dict[str, Any]) -> RawRecord:
    return RawRecord(
        resource="enrollments",
        record_key=stable_record_key(
            first_value(student, "user_id", "student_id", "id"),
            batch.get("master_batch_id"),
            batch.get("bundle_id"),
            batch.get("class_id"),
            payload=student,
        ),
        payload=student,
        request_context=batch,
    )
