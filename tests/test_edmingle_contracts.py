from __future__ import annotations

import pytest

from api_scripts.common.api_client import ApiContractError
from api_scripts.common.edmingle import find_record_list, flatten_master_batches, require_record_list


def test_flatten_master_batches_preserves_raw_batch_and_context() -> None:
    raw_batch = {"class_id": 7, "classes": [[11]], "class_name": "A"}
    courses = [{"bundle_id": 5, "bundle_name": "Course", "batch": [raw_batch]}]

    [(payload, context, key)] = flatten_master_batches(courses, 0)

    assert payload is raw_batch
    assert context["bundle_id"] == 5
    assert context["master_batch_id"] == 11
    assert key


def test_require_record_list_rejects_mixed_values() -> None:
    with pytest.raises(ApiContractError):
        require_record_list({"data": [{"ok": True}, "bad"]}, "data", "test")


def test_find_record_list_accepts_nested_catalogue() -> None:
    rows = [{"course_id": 1}]
    assert find_record_list({"response": {"items": rows}}, "test") == rows
