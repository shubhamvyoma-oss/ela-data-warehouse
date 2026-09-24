from __future__ import annotations

import os
from typing import Any

from api_scripts.common.edmingle import require_record_list
from api_scripts.common.repositories import utc_iso
from api_scripts.common.runtime import JobRuntime

# Bronze table this job writes into. Real columns were confirmed against
# the live database before this was written -- see api_scripts/students/README.md.
TABLE = "bronze.students"

# Column order here must exactly match the order of values built in _student_row().
# pipeline_run_id / received_at / id / created_at are populated by
# TransformedTableRepository.write_with_checkpoint itself and are not listed here.
COLUMNS = [
    "user_id",
    "name",
    "email",
    "contact_number",
    "contact_number_2",
    "contact_number_2_country_id",
    "contact_number_2_dial_code",
    "contact_number_country_id",
    "contact_number_dial_code",
    "registration_date",
    "formatted_registration_date",
    "is_archived",
    "parent_contact_number",
    "parent_contact_number_country_id",
    "parent_contact_number_dial_code",
    "parent_email",
    "parent_name",
    "registration_number",
    "role",
    "status",
    "registration_time",
    "user_username",
    "custom_phone_number",
    "custom_age",
    "custom_last_name",
    "custom_user_name",
]

# bronze.students has a UNIQUE constraint on user_id; TransformedTableRepository
# turns this into ON CONFLICT (user_id) DO UPDATE SET <every other column>,
# i.e. last-write-wins per user_id -- the same merge semantics as the original
# script's merge_students() (dedupe by user_id, newly-fetched row overwrites).
UNIQUE_COLUMNS = ["user_id"]

# Custom fields are position-based in each student's customfield_data list.
# Index values are copied verbatim from the original edmingle_student_course_sync.py
# (index_mapping = {"PhoneNumber": 19, "Age": 9, "LastName": 6, "UserName": 0}).
CUSTOM_FIELD_INDEX = {
    "custom_phone_number": 19,  # PhoneNumber
    "custom_age": 9,  # Age
    "custom_last_name": 6,  # LastName
    "custom_user_name": 0,  # UserName
}

DEFAULT_STUDENTS_PER_PAGE = 500


class StudentsJob:
    """Ports the student-roster half of edmingle_student_course_sync.py.

    The original script paced through pages with a resume/overlap mechanism
    tied to its own checkpoint file, because a single run could take 68-80
    hours and needed to survive being killed and restarted partway through a
    page range. That resume/overlap logic is intentionally NOT ported here:
    every page's rows are upserted into bronze.students via
    ON CONFLICT (user_id) DO UPDATE, so a run is idempotent and a later run
    simply re-fetches from page 1 and re-upserts. See README.md for details.
    """

    name = "ela_mis_datasets.students"
    checkpoint_partition_key = "default"

    def run(self, runtime: JobRuntime, checkpoint: dict[str, Any]) -> None:
        # `checkpoint` (the last-committed checkpoint) is intentionally not used
        # to pick a resume page -- see the class docstring and README.md.
        organization_id = runtime.client.settings.organization_id
        per_page = _students_per_page()
        page = 1
        total_students_seen = 0

        while True:
            payload = runtime.client.get_json(
                "/organization/students",
                params={
                    "organization_id": organization_id,
                    "is_archived": 0,
                    "per_page": per_page,
                    "page": page,
                },
                context=f"students page={page}",
            )
            students = require_record_list(payload, "students", "organization students response")
            if not students:
                # Empty page means every student has been fetched.
                break

            total_students_seen += len(students)
            rows = [row for row in (_student_row(student) for student in students) if row is not None]

            runtime.commit_rows(
                table=TABLE,
                columns=COLUMNS,
                rows=rows,
                unique_columns=UNIQUE_COLUMNS,
                checkpoint={
                    "last_page_fetched": page,
                    "total_students_seen": total_students_seen,
                    "updated_at": utc_iso(),
                },
                partition_key=self.checkpoint_partition_key,
            )
            page += 1


def _students_per_page() -> int:
    raw = os.getenv("STUDENTS_PER_PAGE")
    if raw is None or not raw.strip():
        return DEFAULT_STUDENTS_PER_PAGE
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_STUDENTS_PER_PAGE
    return value if value > 0 else DEFAULT_STUDENTS_PER_PAGE


def _student_row(student: dict[str, Any]) -> tuple[Any, ...] | None:
    user_id = _text(student.get("user_id"))
    if not user_id:
        # No usable user_id -- can't satisfy the NOT NULL / UNIQUE column, skip.
        return None

    customfield_data = student.get("customfield_data")
    return (
        user_id,
        _text(student.get("name")),
        _text(student.get("email")),
        _text(student.get("contact_number")),
        _text(student.get("contact_number_2")),
        _text(student.get("contact_number_2_country_id")),
        _text(student.get("contact_number_2_dial_code")),
        _text(student.get("contact_number_country_id")),
        _text(student.get("contact_number_dial_code")),
        _text(student.get("date")),
        _text(student.get("formatted_date")),
        _bool_or_none(student.get("is_archived")),
        _text(student.get("parent_contact_number")),
        _text(student.get("parent_contact_number_country_id")),
        _text(student.get("parent_contact_number_dial_code")),
        _text(student.get("parent_email")),
        _text(student.get("parent_name")),
        _text(student.get("registration_number")),
        _text(student.get("role")),
        _text(student.get("status")),
        _text(student.get("time")),
        _text(student.get("user_username")),
        _text(_custom_field_value(customfield_data, CUSTOM_FIELD_INDEX["custom_phone_number"])),
        _text(_custom_field_value(customfield_data, CUSTOM_FIELD_INDEX["custom_age"])),
        _text(_custom_field_value(customfield_data, CUSTOM_FIELD_INDEX["custom_last_name"])),
        _text(_custom_field_value(customfield_data, CUSTOM_FIELD_INDEX["custom_user_name"])),
    )


def _custom_field_value(customfield_data: Any, index: int) -> Any:
    # Guard against short/missing customfield_data lists -- treat as None.
    if not isinstance(customfield_data, list) or index < 0 or index >= len(customfield_data):
        return None
    entry = customfield_data[index]
    if not isinstance(entry, dict):
        return None
    value = entry.get("field_value")
    return value if value not in (None, "") else None


def _text(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _bool_or_none(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    try:
        return bool(int(value))
    except (TypeError, ValueError):
        return None
