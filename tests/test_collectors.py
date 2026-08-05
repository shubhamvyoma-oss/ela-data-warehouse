from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

from api_scripts.attendance.collector import AttendanceCollector
from api_scripts.course_catalogue.collector import CourseCatalogueCollector
from api_scripts.enrollments.collector import EnrollmentCollector
from api_scripts.master_batches.collector import MasterBatchCollector


class FakeClient:
    def __init__(self, handler: Callable[[str, dict[str, Any]], dict[str, Any]]) -> None:
        self.settings = SimpleNamespace(
            api_key="test-only",
            organization_id="683",
            institute_id="683",
            batches_per_page=321,
            students_per_page=123,
        )
        self.handler = handler
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get_json(
        self, path: str, *, params: dict[str, Any], context: str
    ) -> dict[str, Any]:
        del context
        self.calls.append((path, params))
        return self.handler(path, params)


class FakeRuntime:
    def __init__(self, client: FakeClient) -> None:
        self.client = client
        self.commits: list[tuple[list[Any], dict[str, Any], str]] = []
        self.last_checkpoint: dict[str, Any] = {}

    def commit(
        self,
        records: list[Any],
        checkpoint: dict[str, Any],
        *,
        partition_key: str = "default",
    ) -> int:
        self.commits.append((records, checkpoint, partition_key))
        self.last_checkpoint = dict(checkpoint)
        return len(records)


def _single_batch_response(status: int) -> dict[str, Any]:
    if status != 0:
        return {"courses": [], "page_context": {"has_more_page": False}}
    return {
        "courses": [
            {
                "bundle_id": 10,
                "bundle_name": "Course",
                "batch": [
                    {
                        "class_id": 20,
                        "classes": [[30]],
                        "class_name": "Batch",
                        "start_date": "2026-01-01",
                        "end_date": "2026-12-31",
                    }
                ],
            }
        ],
        "page_context": {"has_more_page": False},
    }


def test_attendance_uses_confirmed_report_contract_and_daily_checkpoint(
    monkeypatch,
) -> None:
    monkeypatch.setenv("ATTENDANCE_START_DATE", "2026-07-01")
    monkeypatch.setenv("ATTENDANCE_END_DATE", "2026-07-01")
    client = FakeClient(lambda _path, _params: {"data": [{"student_Id": 1}]})
    runtime = FakeRuntime(client)

    AttendanceCollector().run(runtime, {})

    path, params = client.calls[0]
    records, checkpoint, partition = runtime.commits[0]
    assert path == "/report/csv"
    assert params["report_type"] == 55
    assert params["response_type"] == 1
    assert params["ORGID"] == "683"
    assert len(records) == 1
    assert checkpoint["last_completed_date"] == "2026-07-01"
    assert partition == "daily"
    assert AttendanceCollector.checkpoint_partition_key == "daily"


def test_course_catalogue_uses_confirmed_response_key_and_accepts_empty_list() -> None:
    client = FakeClient(lambda _path, _params: {"response": []})
    runtime = FakeRuntime(client)

    CourseCatalogueCollector().run(runtime, {})

    assert client.calls == [
        ("/institute/683/courses/catalogue", {"institution_id": "683"})
    ]
    assert runtime.commits[0][0] == []


def test_master_batches_collects_all_statuses_with_configured_page_size() -> None:
    client = FakeClient(
        lambda _path, params: _single_batch_response(int(params["status"]))
    )
    runtime = FakeRuntime(client)

    MasterBatchCollector().run(runtime, {})

    status_calls = [params for _path, params in client.calls]
    assert [params["status"] for params in status_calls] == [0, 1, 3]
    assert all(params["per_page"] == 321 for params in status_calls)
    records = [record for commit, _checkpoint, _partition in runtime.commits for record in commit]
    assert len(records) == 1
    assert records[0].request_context["master_batch_id"] == 30


def test_enrollments_use_batch_index_and_raw_student_payload() -> None:
    raw_student = {"user_id": 99, "email": "person@example.invalid"}

    def handler(path: str, params: dict[str, Any]) -> dict[str, Any]:
        if path == "/short/masterbatch":
            return _single_batch_response(int(params["status"]))
        assert path == "/masterbatch/classstudents"
        return {"students": [raw_student], "page_context": {"has_more_page": False}}

    client = FakeClient(handler)
    runtime = FakeRuntime(client)

    EnrollmentCollector().run(runtime, {})

    batch_calls = [params for path, params in client.calls if path == "/short/masterbatch"]
    student_calls = [
        params for path, params in client.calls if path == "/masterbatch/classstudents"
    ]
    assert all(params["per_page"] == 321 for params in batch_calls)
    assert student_calls == [
        {
            "class_id": 20,
            "master_batch_id": 30,
            "page": 1,
            "per_page": 123,
            "ORGID": "683",
        }
    ]
    records = [record for commit, _checkpoint, _partition in runtime.commits for record in commit]
    assert len(records) == 1
    assert records[0].payload is raw_student
    assert records[0].request_context["bundle_id"] == 10
    assert runtime.last_checkpoint["in_progress"] is False
