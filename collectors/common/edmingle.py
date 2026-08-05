from __future__ import annotations

from typing import Any

from collectors.common.api_client import ApiContractError
from collectors.common.models import first_value, stable_record_key

BATCH_STATUSES = (0, 1, 3)


def require_record_list(payload: dict[str, Any], key: str, context: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ApiContractError(f"{context} did not contain a valid {key!r} record list")
    return value


def find_record_list(payload: dict[str, Any], context: str) -> list[dict[str, Any]]:
    for preferred_key in ("courses", "data", "records", "result"):
        value = payload.get(preferred_key)
        if isinstance(value, list) and all(isinstance(item, dict) for item in value):
            return value

    def walk(value: Any) -> list[dict[str, Any]] | None:
        if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
            return value
        if isinstance(value, dict):
            for nested in value.values():
                found = walk(nested)
                if found is not None:
                    return found
        return None

    found = walk(payload)
    if found is None:
        raise ApiContractError(f"{context} did not contain a record list")
    return found


def flatten_master_batches(
    courses: list[dict[str, Any]], batch_status: int
) -> list[tuple[dict[str, Any], dict[str, Any], str]]:
    rows: list[tuple[dict[str, Any], dict[str, Any], str]] = []
    for course in courses:
        batches = course.get("batch", [])
        if not isinstance(batches, list):
            raise ApiContractError("master batch response contained a non-list batch value")
        for batch in batches:
            if not isinstance(batch, dict):
                raise ApiContractError("master batch response contained a non-object batch")
            classes = batch.get("classes", [])
            master_batch_id: Any = None
            if isinstance(classes, list) and classes:
                first_class = classes[0]
                if isinstance(first_class, list) and first_class:
                    master_batch_id = first_class[0]
                elif isinstance(first_class, str | int):
                    master_batch_id = first_class
            class_id = first_value(batch, "class_id", "classId")
            context = {
                "bundle_id": first_value(course, "bundle_id", "bundleId"),
                "bundle_name": first_value(course, "bundle_name", "bundleName"),
                "batch_status": batch_status,
                "class_id": class_id,
                "master_batch_id": master_batch_id,
            }
            key = stable_record_key(
                context["bundle_id"], master_batch_id, class_id, payload=batch
            )
            rows.append((batch, context, key))
    return rows


def has_more_pages(payload: dict[str, Any]) -> bool:
    page_context = payload.get("page_context", {})
    return isinstance(page_context, dict) and bool(page_context.get("has_more_page", False))
