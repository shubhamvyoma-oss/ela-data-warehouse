from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any

from api_scripts.common.api_client import ApiContractError
from api_scripts.common.edmingle import has_more_pages, require_record_list
from api_scripts.common.repositories import utc_iso
from api_scripts.common.runtime import JobRuntime

# Same DD-MM-YYYY format the original edmingle_constants.DATE_FMT used --
# this is the format Edmingle's /reports/enrollment endpoint expects for
# start_date/end_date, not an internal choice.
DATE_FMT = "%d-%m-%Y"

# Columns of bronze.enrollment_reports, in the exact order commit_rows() will
# insert them (pipeline_run_id / received_at / id / created_at are added by
# TransformedTableRepository or default at the DB level). This list is a
# direct port of FIELDS from the original edmingle_constants.py -- same
# names, same order.
COLUMNS = [
    "enrollment_id",
    "enrollment_day",
    "user_id",
    "name",
    "email",
    "contact_number",
    "contact_number_country_id",
    "state",
    "registration_number",
    "learner_type",
    "enrollment_mode",
    "enrollment_status",
    "bundle_id",
    "bundle_name",
    "batch_ids",
    "batches",
    "product_type",
    "product_type_label",
    "platform_type",
    "enrollment_expiration_date",
    "shipping_details_json",
    "preferred_categories",
]

UNIQUE_COLUMNS = ["enrollment_id"]

# Not present in the original script's per-field logic: bronze.enrollment_reports
# stores every column as `text`, so any field the API returns as a list/dict
# (e.g. batch_ids, shipping_details_json) needs to become a string before it can
# be inserted. The original CSV writer did this implicitly -- csv.DictWriter
# stringifies non-string values with str() -- so this reproduces that exact
# behavior rather than reformatting as JSON.
def _field_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def build_chunks(start_date: str, end_date: str, chunk_days: int) -> list[tuple[str, str]]:
    """Split [start_date, end_date] (DD-MM-YYYY, inclusive) into windows of at
    most chunk_days days each, returned as a list of (start, end) strings in
    the same DD-MM-YYYY format the API expects.

    Ported near-verbatim from the original edmingle_chunker.build_chunks --
    this is genuine business logic (how much history to request per call,
    because Edmingle rejects overly large single-shot date ranges), not just
    HTTP mechanics, so it is kept as its own explicit function rather than
    folded into the shared common/ API-client infra. The only change from the
    original is raising ValueError instead of calling sys.exit(), since this
    runs inside a job rather than as a standalone CLI script.
    """
    start = datetime.strptime(start_date, DATE_FMT)
    end = datetime.strptime(end_date, DATE_FMT)
    if start > end:
        raise ValueError("ENROLLMENT_REPORTS_START_DATE must not be after ENROLLMENT_REPORTS_END_DATE")

    chunks: list[tuple[str, str]] = []
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=chunk_days - 1), end)
        chunks.append((cur.strftime(DATE_FMT), chunk_end.strftime(DATE_FMT)))
        cur = chunk_end + timedelta(days=1)
    return chunks


def _build_row(student: dict[str, Any]) -> tuple[Any, ...]:
    """Maps one 'studentlist' entry from the enrollment report endpoint onto a
    bronze.enrollment_reports row, in COLUMNS order. Matches the original
    script's field handling exactly: extra API fields are dropped (only
    COLUMNS are read off the row), and a field missing from the response is
    treated the same as one present with a None value."""
    return tuple(_field_value(student.get(column)) for column in COLUMNS)


def _load_window() -> tuple[str, str, int, int]:
    start_date = os.getenv("ENROLLMENT_REPORTS_START_DATE", "").strip()
    end_date = os.getenv("ENROLLMENT_REPORTS_END_DATE", "").strip()
    if not start_date:
        raise ValueError("ENROLLMENT_REPORTS_START_DATE is required (DD-MM-YYYY)")
    if not end_date:
        raise ValueError("ENROLLMENT_REPORTS_END_DATE is required (DD-MM-YYYY)")

    chunk_days_raw = os.getenv("ENROLLMENT_REPORTS_CHUNK_DAYS", "").strip()
    chunk_days = int(chunk_days_raw) if chunk_days_raw else 30
    if chunk_days < 1:
        raise ValueError("ENROLLMENT_REPORTS_CHUNK_DAYS must be a positive integer")

    # Not one of the original script's env vars (it read per_page out of
    # edmingle_config.json instead) -- added here since this port has no
    # equivalent job-specific config file. Default of 100 matches the
    # students_per_page/batches_per_page defaults already used elsewhere in
    # EdmingleSettings.
    per_page_raw = os.getenv("ENROLLMENT_REPORTS_PER_PAGE", "").strip()
    per_page = int(per_page_raw) if per_page_raw else 100
    if per_page < 1:
        raise ValueError("ENROLLMENT_REPORTS_PER_PAGE must be a positive integer")

    return start_date, end_date, chunk_days, per_page


class EnrollmentReportsJob:
    """Ports edmingle_export.py / edmingle_api.py / edmingle_chunker.py --
    GET /reports/enrollment (report_details_type=3), a row-level enrollment
    extract pulled in <=chunk_days date windows because Edmingle rejects
    overly large single-shot ranges.

    This is a distinct data source from bronze.course_enrollments (which
    ports edmingle_student_course_sync.py's GET /admin/classes/attendance
    call): different endpoint, different upstream script, different shape.
    course_enrollments is a per-student attendance/roster join; this job is
    Edmingle's own enrollment report, one row per enrollment event.

    HTTP retries, backoff, and rate limiting are handled by the shared
    EdmingleApiClient (runtime.client.get_json) instead of the original
    script's hand-rolled RollingRateLimiter/backoff in edmingle_api.py --
    that mechanics layer is superseded by the shared client. Only
    build_chunks() (a genuine business decision about how the date range is
    partitioned, not HTTP mechanics) is kept as this job's own logic rather
    than folded into common/.
    """

    name = "enrollment_reports"
    checkpoint_partition_key = "default"

    def run(self, runtime: JobRuntime, checkpoint: dict[str, Any]) -> None:
        start_date, end_date, chunk_days, per_page = _load_window()
        chunks = build_chunks(start_date, end_date, chunk_days)

        chunks_completed = int(checkpoint.get("chunks_completed", 0))
        if chunks_completed < 0 or chunks_completed > len(chunks):
            # The window/chunk_days changed between runs and no longer lines
            # up with this checkpoint -- restart safely from the beginning
            # rather than skipping or indexing out of range. The UNIQUE
            # constraint on enrollment_id makes re-fetching earlier chunks
            # harmless (upsert, not duplicate).
            chunks_completed = 0

        if not chunks:
            runtime.commit_rows(
                table="bronze.enrollment_reports",
                columns=COLUMNS,
                rows=[],
                unique_columns=UNIQUE_COLUMNS,
                checkpoint={"chunks_completed": 0, "total_chunks": 0, "updated_at": utc_iso()},
            )
            return

        for chunk_index in range(chunks_completed, len(chunks)):
            chunk_start, chunk_end = chunks[chunk_index]
            rows: list[tuple[Any, ...]] = []
            page = 1

            while True:
                context = f"enrollment reports chunk={chunk_start}..{chunk_end} page={page}"
                payload = runtime.client.get_json(
                    "/reports/enrollment",
                    params={
                        "start_date": chunk_start,
                        "end_date": chunk_end,
                        "time_step": 1,
                        "report_details_type": 3,
                        "page": page,
                        "per_page": per_page,
                        "sort_order": "D",
                        "sort_by": "date_of_enrolment",
                        "currency_id": 1,
                    },
                    context=context,
                )

                # EdmingleApiClient.get_json already rejects HTTP-level errors
                # and Edmingle's own error_code 6001/6002 application errors,
                # but not an unexpected non-200 `code` inside an otherwise
                # well-formed 200 response -- so this reproduces the original
                # fetch_page's explicit `data["code"] == 200` check.
                if payload.get("code") != 200:
                    raise ApiContractError(f"{context} returned an unexpected response code")

                result = payload.get("result")
                students = require_record_list(
                    result if isinstance(result, dict) else {}, "studentlist", context
                )
                rows.extend(_build_row(student) for student in students)

                if not has_more_pages(payload):
                    break
                page += 1

            runtime.commit_rows(
                table="bronze.enrollment_reports",
                columns=COLUMNS,
                rows=rows,
                unique_columns=UNIQUE_COLUMNS,
                checkpoint={
                    "chunks_completed": chunk_index + 1,
                    "total_chunks": len(chunks),
                    "updated_at": utc_iso(),
                },
            )
