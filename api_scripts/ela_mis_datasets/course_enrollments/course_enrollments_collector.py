from __future__ import annotations

from typing import Any

from api_scripts.common.edmingle import require_record_list
from api_scripts.common.repositories import utc_iso
from api_scripts.common.runtime import CollectorRuntime
from shared.config import DatabaseSettings
from shared.database import Database

# Columns of bronze.course_enrollments, in the exact order commit_rows() will
# insert them (pipeline_run_id / received_at / id / created_at are added by
# TransformedTableRepository or default at the DB level).
COLUMNS = [
    "user_id",
    "name",
    "email",
    "class_id",
    "class_name",
    "tutor_name",
    "total_classes",
    "present_count",
    "absent_count",
    "late_count",
    "excused_count",
    "start_date",
    "end_date",
    "master_batch_id",
    "master_batch_name",
    "classusers_start_date",
    "classusers_end_date",
    "batch_status",
    "cu_status",
    "cu_state",
    "institution_bundle_id",
    "archived_at",
    "bundle_id",
]

UNIQUE_COLUMNS = ["user_id", "class_id"]

# Students per commit_rows() call -- a batching choice for transaction overhead,
# not a fidelity requirement. The original script checkpointed after every
# single student; upserting on (user_id, class_id) makes that unnecessary here.
STUDENTS_PER_BATCH = 100


def _text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _numeric(value: Any) -> Any:
    if value is None or value == "":
        return None
    return value


def _build_row(user_id: str, course: dict[str, Any]) -> tuple[Any, ...] | None:
    """Maps one 'classes' entry from the attendance endpoint onto a
    bronze.course_enrollments row. Field names on the Edmingle side
    (class_id, present, absent, ...) match COURSE_FIELDS in the original
    script exactly -- these are the API's own field names, not something the
    original script renamed. Only present/absent/late/excused get renamed
    here, to match the *_count column names already chosen for the table."""
    class_id = course.get("class_id")
    if class_id is None or class_id == "":
        # bronze.course_enrollments.class_id is NOT NULL; skip rows the API
        # returns without one rather than failing the whole batch.
        return None
    return (
        user_id,
        _text(course.get("name")),
        _text(course.get("email")),
        _text(class_id),
        _text(course.get("class_name")),
        _text(course.get("tutor_name")),
        _numeric(course.get("total_classes")),
        _numeric(course.get("present")),
        _numeric(course.get("absent")),
        _numeric(course.get("late")),
        _numeric(course.get("excused")),
        _text(course.get("start_date")),
        _text(course.get("end_date")),
        _text(course.get("master_batch_id")),
        _text(course.get("master_batch_name")),
        _text(course.get("classusers_start_date")),
        _text(course.get("classusers_end_date")),
        _text(course.get("batch_status")),
        _text(course.get("cu_status")),
        _text(course.get("cu_state")),
        _text(course.get("institution_bundle_id")),
        _text(course.get("archived_at")),
        _text(course.get("bundle_id")),
    )


class CourseEnrollmentsCollector:
    """Ports the course/enrollment half of the legacy
    edmingle_student_course_sync.py script (the student-roster half is ported
    separately as the `students` job). One GET /admin/classes/attendance call
    per eligible student; each call's `classes` list becomes one row per
    class session for that student.

    Depends on the `students` job having already run: the eligible user_id
    list is read from bronze.students rather than from an in-memory/CSV
    source, matching this project's pattern of a downstream job reading an
    upstream job's committed Bronze table (e.g. class_id_lookup -> catalogue)
    instead of re-deriving the list itself.
    """

    name = "ela_mis_datasets.course_enrollments"
    checkpoint_partition_key = "default"

    def run(self, runtime: CollectorRuntime, checkpoint: dict[str, Any]) -> None:
        user_ids = self._load_eligible_user_ids()

        already_processed = int(checkpoint.get("students_processed", 0))
        if already_processed < 0 or already_processed > len(user_ids):
            # bronze.students shrank or changed shape between runs -- restart
            # safely rather than indexing out of range or skipping students.
            already_processed = 0

        if not user_ids:
            runtime.commit_rows(
                table="bronze.course_enrollments",
                columns=COLUMNS,
                rows=[],
                unique_columns=UNIQUE_COLUMNS,
                checkpoint={"students_processed": 0, "updated_at": utc_iso()},
            )
            return

        pending_rows: list[tuple[Any, ...]] = []
        processed = already_processed

        for index in range(already_processed, len(user_ids)):
            user_id = user_ids[index]
            context = f"course enrollments user_id={user_id}"
            payload = runtime.client.get_json(
                "/admin/classes/attendance",
                params={"user_id": user_id, "response_type": 1},
                context=context,
            )
            classes = require_record_list(payload, "classes", context)
            for course in classes:
                row = _build_row(user_id, course)
                if row is not None:
                    pending_rows.append(row)

            processed = index + 1

            if processed % STUDENTS_PER_BATCH == 0 or processed == len(user_ids):
                runtime.commit_rows(
                    table="bronze.course_enrollments",
                    columns=COLUMNS,
                    rows=pending_rows,
                    unique_columns=UNIQUE_COLUMNS,
                    checkpoint={"students_processed": processed, "updated_at": utc_iso()},
                )
                pending_rows = []

    def _load_eligible_user_ids(self) -> list[str]:
        # CollectorRuntime has no generic query method, so this job opens its
        # own short-lived read connection just to look up eligible user_ids
        # from bronze.students -- separate from the runtime's own write path.
        database = Database(DatabaseSettings.from_environment(), "course_enrollments-lookup")
        try:
            with database.connection() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT DISTINCT user_id
                    FROM bronze.students
                    WHERE user_id IS NOT NULL AND user_id <> 'NA'
                    ORDER BY user_id
                    """
                )
                return [row[0] for row in cursor.fetchall()]
        finally:
            database.close()
