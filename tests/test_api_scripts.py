from __future__ import annotations

# NOTE: api_scripts.api_key_manager.generate is intentionally NOT tested here --
# it performs a real Edmingle login call plus a real email send by design, and
# there is no safe way to unit test it without mocking requests/smtplib, which
# is out of scope for this pass.

import inspect
from collections.abc import Callable
from datetime import date
from types import SimpleNamespace
from typing import Any

from api_scripts.attendance.collector import (
    BATCH_SUMMARY_TABLE,
    SESSION_TABLE,
    AttendanceCollector,
)
from api_scripts.catalogue.collector import CourseCatalogueCollector
from api_scripts.class_id_lookup.collector import ClassIdLookupCollector
from api_scripts.class_session_attendance.collector import ClassSessionAttendanceCollector
from api_scripts.course_batch_merge.collector import CourseBatchMergeCollector
from api_scripts.course_catalogue_raw.collector import CourseCatalogueRawCollector
from api_scripts.course_enrollments.collector import CourseEnrollmentsCollector
from api_scripts.enrollment_reports.collector import build_chunks
from api_scripts.runner import collector_registry
from api_scripts.students.collector import StudentsCollector


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
        self.commit_rows_calls: list[dict[str, Any]] = []
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

    def commit_rows(
        self,
        *,
        table: str,
        columns: list[str],
        rows: list[tuple[Any, ...]],
        unique_columns: list[str],
        checkpoint: dict[str, Any],
        partition_key: str = "default",
    ) -> int:
        self.commit_rows_calls.append(
            {
                "table": table,
                "columns": columns,
                "rows": rows,
                "unique_columns": unique_columns,
                "checkpoint": checkpoint,
                "partition_key": partition_key,
            }
        )
        self.last_checkpoint = dict(checkpoint)
        return len(rows)


def _calls_for_table(runtime: FakeRuntime, table: str) -> list[dict[str, Any]]:
    return [call for call in runtime.commit_rows_calls if call["table"] == table]


# ═══════════════════════════════════════════════════════════════════
# attendance
# ═══════════════════════════════════════════════════════════════════

_ATTENDANCE_ROW_1 = {
    "batch_Id": 1,
    "student_Id": 100,
    "attendance_id": 500,
    "classDate": "01 Jul 2026",
    "startTime": "10:00 AM",
    "studentAttendanceStatus": "P",
    "studentBatchStatus": "Active",
    "batchName": "B1",
    "course_Id": 10,
    "courseName": "Course1",
    "bundle_Id": 20,
    "bundleName": "Bundle1",
    "teacher_Id": 30,
    "teacherName": "Teacher1",
    "studentRating": 4,
}

_ATTENDANCE_ROW_2 = {
    **_ATTENDANCE_ROW_1,
    "student_Id": 101,
    "studentAttendanceStatus": "A",
    "studentRating": 0,  # excluded from average_rating by default (treated as "not rated")
}


def test_attendance_uses_confirmed_report_contract_and_computes_summaries(monkeypatch) -> None:
    monkeypatch.setenv("ATTENDANCE_START_DATE", "2026-07-01")
    monkeypatch.setenv("ATTENDANCE_END_DATE", "2026-07-01")

    client = FakeClient(lambda _path, _params: {"data": [_ATTENDANCE_ROW_1, _ATTENDANCE_ROW_2]})
    runtime = FakeRuntime(client)

    AttendanceCollector().run(runtime, {})

    assert AttendanceCollector.name == "attendance"
    assert AttendanceCollector.checkpoint_partition_key == "daily"

    # ── endpoint contract: one call, report_type=55 CSV endpoint ──
    assert len(client.calls) == 1
    path, params = client.calls[0]
    assert path == "/report/csv"
    assert params["report_type"] == 55
    assert params["response_type"] == 1
    assert params["ORGID"] == "683"
    assert params["organization_id"] == "683"
    assert params["apikey"] == "test-only"

    session_calls = _calls_for_table(runtime, SESSION_TABLE)
    batch_calls = _calls_for_table(runtime, BATCH_SUMMARY_TABLE)
    assert len(session_calls) == 1
    assert len(batch_calls) == 1
    assert session_calls[0]["partition_key"] == "daily"
    assert batch_calls[0]["partition_key"] == "daily"
    assert session_calls[0]["checkpoint"]["summary_window_start"] == "2026-07-01"
    assert session_calls[0]["checkpoint"]["summary_window_end"] == "2026-07-01"

    # ── session-level summary: 1 present, 1 absent, 50% attendance ──
    session_rows = session_calls[0]["rows"]
    assert len(session_rows) == 1
    session_row = session_rows[0]
    assert session_row[0] == "1"  # batch_id
    assert session_row[1] == "B1"  # batch_name
    assert session_row[4] == 1  # session_number
    assert session_row[5] == "500"  # session_id (attendance_id)
    assert session_row[6] == date(2026, 7, 1)  # class_date
    assert session_row[7] is True  # is_session_conducted
    assert session_row[8] == 1  # present_count
    assert session_row[9] == 1  # absent_count
    assert session_row[10] == 0  # late_count
    assert session_row[11] == 2  # total_marked
    assert session_row[12] == 50.0  # session_attendance_percentage

    # ── batch-level summary: rating=0 excluded, retention/drop computed ──
    batch_rows = batch_calls[0]["rows"]
    assert len(batch_rows) == 1
    batch_row = batch_rows[0]
    assert batch_row[0] == "1"  # batch_id
    assert batch_row[2] == "20"  # bundle_id
    assert batch_row[8] == 2  # total_students_enrolled
    assert batch_row[11] == 1  # first_class_attendance
    assert batch_row[12] == 1  # last_class_attendance
    assert batch_row[15] == 50.0  # attendance_percentage
    assert batch_row[19] == 4.0  # average_rating (0-rating excluded)
    assert batch_row[20] == 100.0  # retention_percentage
    assert batch_row[21] == 0  # attendance_drop


def test_attendance_commits_empty_summaries_when_no_rows_fetched(monkeypatch) -> None:
    monkeypatch.setenv("ATTENDANCE_START_DATE", "2026-07-01")
    monkeypatch.setenv("ATTENDANCE_END_DATE", "2026-07-01")

    client = FakeClient(lambda _path, _params: {"data": []})
    runtime = FakeRuntime(client)

    AttendanceCollector().run(runtime, {})

    session_calls = _calls_for_table(runtime, SESSION_TABLE)
    batch_calls = _calls_for_table(runtime, BATCH_SUMMARY_TABLE)
    assert len(session_calls) == 1
    assert session_calls[0]["rows"] == []
    assert len(batch_calls) == 1
    assert batch_calls[0]["rows"] == []


# ═══════════════════════════════════════════════════════════════════
# catalogue (CourseCatalogueCollector -- primary catalogue builder)
# ═══════════════════════════════════════════════════════════════════

# _FIELD_MAP column indices shared by catalogue and course_batch_merge (identical map).
_BUNDLE_ID_IDX = 0
_BATCH_ID_IDX = 2
_IS_LATEST_BATCH_IDX = 37
_HAS_BATCH_IDX = 38
_FINAL_STATUS_IDX = 40

_CATALOGUE_ROWS = [
    {"Bundle id": 20, "Course Name": "Course A", "Status": "Ongoing"},
    {"Bundle id": 99, "Course Name": "Course B (no batch)", "Status": "Upcoming"},
]


def _catalogue_batch_response(status: int) -> dict[str, Any]:
    if status == 0:
        return {
            "courses": [
                {
                    "bundle_id": 20,
                    "bundle_name": "Bundle20",
                    "batch": [
                        {
                            "class_id": 201,
                            "class_name": "Batch201",
                            "start_date": "2000000000",
                            "end_date": "2000003600",
                            "tutor_name": "T1",
                            "tutor_id": "9",
                            "admitted_students": 5,
                        }
                    ],
                }
            ]
        }
    if status == 3:
        return {
            "courses": [
                {
                    "bundle_id": 20,
                    "bundle_name": "Bundle20",
                    "batch": [
                        {
                            "class_id": 202,
                            "class_name": "Batch202",
                            "start_date": "1000000000",
                            "end_date": "1000003600",
                            "tutor_name": "T2",
                            "tutor_id": "8",
                            "admitted_students": 3,
                        }
                    ],
                },
                {
                    "bundle_id": 55,
                    "bundle_name": "ExcludedBundleOnly",
                    "batch": [
                        {
                            "class_id": 12458,  # in _BATCH_IDS_TO_EXCLUDE
                            "class_name": "ExcludedBatch",
                            "start_date": "900000000",
                            "end_date": "900003600",
                        }
                    ],
                },
            ]
        }
    raise AssertionError(f"unexpected status {status}")


def _catalogue_handler(path: str, params: dict[str, Any]) -> dict[str, Any]:
    if path == "/institute/683/courses/catalogue":
        assert params == {"institution_id": "683"}
        return {"response": _CATALOGUE_ROWS}
    assert path == "/short/masterbatch"
    return _catalogue_batch_response(int(params["status"]))


def test_catalogue_fetches_active_and_completed_only_and_excludes_bad_batch_ids() -> None:
    client = FakeClient(_catalogue_handler)
    runtime = FakeRuntime(client)

    CourseCatalogueCollector().run(runtime, {})

    assert CourseCatalogueCollector.name == "catalogue"

    masterbatch_calls = [(p, params) for p, params in client.calls if p == "/short/masterbatch"]
    statuses_called = sorted(params["status"] for _p, params in masterbatch_calls)
    assert statuses_called == [0, 3]  # never fetches Archived (status=1)
    assert all(params["per_page"] == 1000 for _p, params in masterbatch_calls)

    calls = _calls_for_table(runtime, "bronze.course_catalog")
    assert len(calls) == 1
    assert calls[0]["unique_columns"] == ["batch_id", "bundle_id"]

    rows = calls[0]["rows"]
    # excluded batch_id 12458 must never appear in the output
    assert all(row[_BATCH_ID_IDX] != "12458" for row in rows)
    assert len(rows) == 3  # batch201 + batch202 + synthetic bundle99 (no-batch course)

    batch201 = next(row for row in rows if row[_BATCH_ID_IDX] == "201")
    assert batch201[_IS_LATEST_BATCH_IDX] is True
    assert batch201[_FINAL_STATUS_IDX] == "Ongoing"  # latest batch inherits valid catalogue status

    batch202 = next(row for row in rows if row[_BATCH_ID_IDX] == "202")
    assert batch202[_IS_LATEST_BATCH_IDX] is False
    assert batch202[_FINAL_STATUS_IDX] == "Completed"  # non-latest batches default to Completed

    synthetic = next(
        row for row in rows if row[_BATCH_ID_IDX] is None and row[_BUNDLE_ID_IDX] == "99"
    )
    assert synthetic[_HAS_BATCH_IDX] is False
    assert synthetic[_FINAL_STATUS_IDX] == "Upcoming"


# ═══════════════════════════════════════════════════════════════════
# course_batch_merge (fetches ALL THREE statuses, including Archived)
# ═══════════════════════════════════════════════════════════════════

_MERGE_CATALOGUE_ROWS = [
    {"Bundle id": 3, "Course Name": "Real Course", "Status": "Completed"},
    {"Bundle id": 4, "Course Name": "NoBatchCourse", "Status": "Upcoming"},
]


def _merge_batch_response(status: int) -> dict[str, Any]:
    if status == 0:
        return {
            "courses": [
                {
                    "bundle_id": 1,
                    "bundle_name": "Bundle1",
                    "batch": [
                        {
                            "class_id": 11,
                            "class_name": "Test Batch A",  # filtered: name contains "test batch"
                            "start_date": "100",
                            "end_date": "200",
                        }
                    ],
                }
            ]
        }
    if status == 1:
        return {
            "courses": [
                {
                    "bundle_id": 2,
                    "bundle_name": "Demo Bundle",  # filtered: no catalogue match + "demo" keyword
                    "batch": [
                        {
                            "class_id": 22,
                            "class_name": "Batch22",
                            "start_date": "50",
                            "end_date": "60",
                        }
                    ],
                }
            ]
        }
    if status == 3:
        return {
            "courses": [
                {
                    "bundle_id": 3,
                    "bundle_name": "RealBundle",
                    "batch": [
                        {
                            "class_id": 33,
                            "class_name": "Batch33",
                            "start_date": "10",
                            "end_date": "20",
                        }
                    ],
                }
            ]
        }
    raise AssertionError(f"unexpected status {status}")


def _merge_handler(path: str, params: dict[str, Any]) -> dict[str, Any]:
    if path == "/institute/683/courses/catalogue":
        return {"response": _MERGE_CATALOGUE_ROWS}
    assert path == "/short/masterbatch"
    return _merge_batch_response(int(params["status"]))


def test_course_batch_merge_fetches_all_statuses_and_filters_test_batches_and_courses() -> None:
    client = FakeClient(_merge_handler)
    runtime = FakeRuntime(client)

    CourseBatchMergeCollector().run(runtime, {})

    assert CourseBatchMergeCollector.name == "course_batch_merge"

    masterbatch_calls = [(p, params) for p, params in client.calls if p == "/short/masterbatch"]
    statuses_called = sorted(params["status"] for _p, params in masterbatch_calls)
    assert statuses_called == [0, 1, 3]  # includes Archived, unlike `catalogue`

    calls = _calls_for_table(runtime, "bronze.course_batch_merge")
    assert len(calls) == 1
    assert calls[0]["unique_columns"] == ["batch_id", "bundle_id"]

    rows = calls[0]["rows"]
    batch_ids = {row[_BATCH_ID_IDX] for row in rows}
    assert "11" not in batch_ids  # dropped: batch name contains "test batch"
    assert "22" not in batch_ids  # dropped: no catalogue match + "demo" keyword in bundle name
    assert "33" in batch_ids  # kept: has a catalogue match

    batch33 = next(row for row in rows if row[_BATCH_ID_IDX] == "33")
    assert batch33[_FINAL_STATUS_IDX] == "Completed"

    synthetic = next(
        row for row in rows if row[_BATCH_ID_IDX] is None and row[_BUNDLE_ID_IDX] == "4"
    )
    assert synthetic[_HAS_BATCH_IDX] is False
    assert synthetic[_FINAL_STATUS_IDX] == "Upcoming"


# ═══════════════════════════════════════════════════════════════════
# course_catalogue_raw (single GET, recursive list-finder + flatten + hash)
# ═══════════════════════════════════════════════════════════════════


def test_course_catalogue_raw_flattens_and_hashes_rows() -> None:
    payload = {"response": [{"Bundle id": 5, "bundle_id": 500, "Course Name": "X"}]}
    client = FakeClient(lambda _path, _params: payload)
    runtime = FakeRuntime(client)

    CourseCatalogueRawCollector().run(runtime, {})

    assert CourseCatalogueRawCollector.name == "course_catalogue_raw"

    assert client.calls == [
        ("/institute/683/courses/catalogue", {"institution_id": "683"})
    ]

    calls = _calls_for_table(runtime, "bronze.course_catalogue_raw")
    assert len(calls) == 1
    assert calls[0]["columns"] == ["bundle_id", "row_sha256", "raw_payload"]
    assert calls[0]["unique_columns"] == ["bundle_id", "row_sha256"]

    rows = calls[0]["rows"]
    assert len(rows) == 1
    row = rows[0]
    assert row[0] == 5  # priority: "Bundle id" wins when both keys are present
    row_sha256 = row[1]
    assert isinstance(row_sha256, str)
    assert len(row_sha256) == 64  # sha256 hex digest


def test_course_catalogue_raw_falls_back_to_bundle_id_key() -> None:
    # Only "bundle_id" is present across the whole batch (no "Bundle id" key
    # at all), so pd.json_normalize never creates a "Bundle id" column and
    # row.get("Bundle id") is genuinely absent (None), letting extraction
    # fall through to "bundle_id". NOTE: this fallback only behaves this way
    # when NO record in the batch has "Bundle id" -- if some records did and
    # others didn't, json_normalize would still create the column and backfill
    # the gap with NaN (not None), which `value is not None` treats as
    # "present", silently defeating the fallback for those rows. That's a
    # real quirk in the ported (out-of-scope) source, not something to paper
    # over in this test.
    payload = {"response": [{"bundle_id": 7, "Course Name": "Y"}]}
    client = FakeClient(lambda _path, _params: payload)
    runtime = FakeRuntime(client)

    CourseCatalogueRawCollector().run(runtime, {})

    rows = _calls_for_table(runtime, "bronze.course_catalogue_raw")[0]["rows"]
    assert len(rows) == 1
    assert rows[0][0] == 7


# ═══════════════════════════════════════════════════════════════════
# students
# ═══════════════════════════════════════════════════════════════════

_STUDENT_A_CUSTOM_FIELDS = [{"field_value": None} for _ in range(20)]
_STUDENT_A_CUSTOM_FIELDS[0] = {"field_value": "alice_uname"}
_STUDENT_A_CUSTOM_FIELDS[6] = {"field_value": "Doe"}
_STUDENT_A_CUSTOM_FIELDS[9] = {"field_value": "21"}
_STUDENT_A_CUSTOM_FIELDS[19] = {"field_value": "9999999999"}

_STUDENT_A = {
    "user_id": 1,
    "name": "Alice",
    "email": "alice@example.invalid",
    "customfield_data": _STUDENT_A_CUSTOM_FIELDS,
}
_STUDENT_NO_USER_ID = {"user_id": None, "name": "NoId"}


def test_students_paginates_until_empty_page_and_extracts_custom_fields() -> None:
    pages = [
        {"students": [_STUDENT_A, _STUDENT_NO_USER_ID]},
        {"students": []},
    ]

    def handler(path: str, params: dict[str, Any]) -> dict[str, Any]:
        assert path == "/organization/students"
        assert params["organization_id"] == "683"
        assert params["is_archived"] == 0
        assert params["per_page"] == 500
        return pages[params["page"] - 1]

    client = FakeClient(handler)
    runtime = FakeRuntime(client)

    StudentsCollector().run(runtime, {})

    assert StudentsCollector.name == "students"

    assert [params["page"] for _p, params in client.calls] == [1, 2]

    calls = _calls_for_table(runtime, "bronze.students")
    assert len(calls) == 1  # page 2 is empty, so it never reaches commit_rows
    assert calls[0]["unique_columns"] == ["user_id"]
    assert calls[0]["checkpoint"]["last_page_fetched"] == 1
    assert calls[0]["checkpoint"]["total_students_seen"] == 2  # counts the skipped row too

    rows = calls[0]["rows"]
    assert len(rows) == 1  # the no-user_id student is skipped entirely
    row = rows[0]
    columns = calls[0]["columns"]
    row_by_column = dict(zip(columns, row))
    assert row_by_column["user_id"] == "1"
    assert row_by_column["name"] == "Alice"
    assert row_by_column["custom_user_name"] == "alice_uname"
    assert row_by_column["custom_last_name"] == "Doe"
    assert row_by_column["custom_age"] == "21"
    assert row_by_column["custom_phone_number"] == "9999999999"


# ═══════════════════════════════════════════════════════════════════
# enrollment_reports -- build_chunks is pure business logic and safe to
# unit test directly, even though run() itself makes live HTTP calls.
# ═══════════════════════════════════════════════════════════════════


def test_enrollment_reports_build_chunks_splits_by_chunk_days() -> None:
    chunks = build_chunks("01-01-2026", "10-01-2026", chunk_days=4)
    assert chunks == [
        ("01-01-2026", "04-01-2026"),
        ("05-01-2026", "08-01-2026"),
        ("09-01-2026", "10-01-2026"),
    ]


def test_enrollment_reports_name_and_registry_match() -> None:
    from api_scripts.enrollment_reports.collector import EnrollmentReportsCollector

    assert EnrollmentReportsCollector.name == "enrollment_reports"
    assert EnrollmentReportsCollector.checkpoint_partition_key == "default"
    assert collector_registry()["enrollment_reports"] is EnrollmentReportsCollector


# ═══════════════════════════════════════════════════════════════════
# class_id_lookup / course_enrollments / class_session_attendance
#
# These three collectors open their OWN `Database` connection inside run()
# to read an upstream job's Bronze table (bronze.course_catalog,
# bronze.students, bronze.class_id_lookup respectively) as well as their
# own output table for resume/checkpoint state. That can't be meaningfully
# unit-tested without either a live Postgres fixture or refactoring them to
# accept an injected connection -- neither is in scope for this pass, so
# below is a lightweight smoke test only (registry identity + run() shape),
# not a behavioral test. This is a real coverage gap, not full coverage.
# ═══════════════════════════════════════════════════════════════════

_DB_DEPENDENT_COLLECTORS = {
    "class_id_lookup": ClassIdLookupCollector,
    "course_enrollments": CourseEnrollmentsCollector,
    "class_session_attendance": ClassSessionAttendanceCollector,
}


def test_db_dependent_collectors_are_registered_with_expected_shape() -> None:
    registry = collector_registry()

    for name, collector_cls in _DB_DEPENDENT_COLLECTORS.items():
        assert registry[name] is collector_cls
        assert collector_cls.name == name
        assert collector_cls.checkpoint_partition_key == "default"

        run_params = list(inspect.signature(collector_cls.run).parameters)
        assert run_params == ["self", "runtime", "checkpoint"]
