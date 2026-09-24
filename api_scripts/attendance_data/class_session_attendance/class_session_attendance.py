from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any

from api_scripts.common.repositories import utc_iso
from api_scripts.common.runtime import JobRuntime
from shared.config import DatabaseSettings
from shared.database import Database

LOGGER = logging.getLogger("warehouse.job")

TABLE = "bronze.class_session_attendance"

# Matches bronze.class_session_attendance's column order (minus
# pipeline_run_id/received_at/id/created_at, which TransformedTableRepository
# adds automatically). Field mapping from the original SESSION_BASE_COLUMNS
# (Attendance data/attendance_crossvalidation.py):
#   total_enrolled_at_session -> same
#   present                   -> present_count
#   not_marked                -> not_marked_count
#   session_duration_min      -> session_duration_minutes
#   session_conducted         -> is_session_conducted
COLUMNS = [
    "session_id",
    "class_id",
    "class_name",
    "master_batch_id",
    "master_batch_name",
    "bundle_id",
    "bundle_name",
    "class_date",
    "total_enrolled_at_session",
    "present_count",
    "not_marked_count",
    "attendance_pct",
    "taken_by_name",
    "individual_batch_attendance",
    "session_start_ist",
    "session_end_ist",
    "session_duration_minutes",
    "is_session_conducted",
    "session_number",
]

# Matches bronze.class_session_attendance's UNIQUE (session_id) constraint.
UNIQUE_COLUMNS = ["session_id"]

ORG_ATTENDANCES_PATH = "/organization/attendances"

# Class-level status codes (0-7) confirmed against the classroom UI, direct
# port of NOT_CONDUCTED_STATUSES from attendance_crossvalidation.py. Only the
# not-conducted set is needed -- every other code (0 NotSignedIn, 1 SignedIn,
# 4 LateSignIn, 5 MissedSignIn, 6 ExcusedAbsent, 7 Absent) counts as
# conducted. The raw numeric status code/label are never stored, only this
# derived boolean.
NOT_CONDUCTED_STATUSES = {2, 3}  # Postponed, Cancelled

IST_OFFSET_SECONDS = 5.5 * 3600


def to_unix(date_str: str) -> int:
    """Parse YYYY-MM-DD as IST midnight -> unix timestamp. Direct port of
    to_unix() from both attendance_crossvalidation.py and
    build_session_attendance.py -- manual +5:30 offset, no pytz/zoneinfo,
    kept exactly as written to avoid drifting from the source pipeline's
    IST-boundary handling."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    utc_dt = dt.replace(tzinfo=UTC)
    return int(utc_dt.timestamp() - IST_OFFSET_SECONDS)


def unix_to_ist(ts: Any, fmt: str = "%Y-%m-%d %H:%M:%S") -> str | None:
    """Convert a UTC unix timestamp to an IST-formatted string. Direct port
    of unix_to_ist() from attendance_crossvalidation.py -- same manual
    +5:30-offset style as to_unix()."""
    if ts is None:
        return None
    dt = datetime.fromtimestamp(ts + IST_OFFSET_SECONDS, tz=UTC)
    return dt.strftime(fmt)


def _id_text(value: Any) -> str | None:
    """Normalize a numeric-looking id (session_id/class_id/master_batch_id)
    to a canonical integer string (e.g. 12345.0 -> "12345"), matching the
    Int64-cast intent of the original pandas pipeline while writing into
    this table's text-typed id columns (see migration
    006_legacy_pipeline_bronze_tables.sql). Same normalize-with-fallback
    approach as class_id_lookup's _normalize_batch_id: a non-numeric value is
    passed through as text rather than dropped."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return str(int(float(text)))
    except (TypeError, ValueError):
        return text


def _text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _session_from_class_row(row: dict[str, Any], bundle_id: Any, bundle_name: Any) -> dict[str, Any] | None:
    """Direct port of sessions_to_dataframe()'s per-row field mapping from
    attendance_crossvalidation.py, plus bundle_id/bundle_name sourced from
    the class_id_lookup row (matching build_session_attendance.py's Stage-3
    behavior of attaching those two fields from its input lookup file, not
    from the API response). Returns None when the row has no session id --
    bronze.class_session_attendance.session_id is NOT NULL, so such a row is
    skipped rather than failing the whole batch (same pattern as
    course_enrollments skipping rows with no class_id)."""
    session_id = _id_text(row.get("id"))
    if session_id is None:
        return None

    gmt_start = row.get("gmt_start_time")
    gmt_end = row.get("gmt_end_time")
    total = row.get("total")
    present = row.get("present")
    master_batch_name = row.get("master_batch_name")

    return {
        "session_id": session_id,
        "class_id": _id_text(row.get("class_id")),
        "class_name": row.get("class_name"),
        "master_batch_id": _id_text(row.get("master_batch_id")),
        "master_batch_name": (
            master_batch_name.strip() if isinstance(master_batch_name, str) else master_batch_name
        ),
        "bundle_id": _text(bundle_id),
        "bundle_name": bundle_name,
        "class_date": unix_to_ist(row.get("class_date"), "%Y-%m-%d"),
        "total_enrolled_at_session": total,
        "present_count": present,
        "not_marked_count": row.get("not_marked"),
        "attendance_pct": round(100 * present / total, 2) if total else None,
        "taken_by_name": row.get("taken_by_name"),
        "individual_batch_attendance": _text(row.get("individual_batch_attendance")),
        "session_start_ist": unix_to_ist(gmt_start),
        "session_end_ist": unix_to_ist(gmt_end),
        "session_duration_minutes": round((gmt_end - gmt_start) / 60, 1) if gmt_start and gmt_end else None,
        "is_session_conducted": row.get("status") not in NOT_CONDUCTED_STATUSES,
        # master_batch_id used as the group key for session_number below --
        # not part of the row's final column set beyond what's already set.
        "_master_batch_id_raw": row.get("master_batch_id"),
    }


def _assign_session_numbers(sessions: list[dict[str, Any]]) -> None:
    """Direct port of sessions_to_dataframe()'s session_number derivation:
    sort by session_start_ist chronologically (None/missing sorts last,
    matching pandas' sort_values default na_position="last"), then number
    sequentially PER master_batch_id in that order (df.groupby(
    "master_batch_id").cumcount() + 1). Intentionally per master_batch_id,
    not per class_id -- this differs from the report55_session_attendance
    pipeline's per-batch_id numbering, see README."""
    sessions.sort(key=lambda s: (s["session_start_ist"] is None, s["session_start_ist"] or ""))
    counters: dict[Any, int] = {}
    for session in sessions:
        key = session["_master_batch_id_raw"]
        counters[key] = counters.get(key, 0) + 1
        session["session_number"] = counters[key]
        del session["_master_batch_id_raw"]


def _row_tuple(session: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(session[column] for column in COLUMNS)


class ClassSessionAttendanceJob:
    """Pulls session-wise attendance for every class_id in
    bronze.class_id_lookup via GET /organization/attendances, direct port of
    'Attendance data/build_session_attendance.py' (Stage 3 of the legacy
    pipeline) plus the shared extract functions it imports from
    'Attendance data/attendance_crossvalidation.py' (fetch_org_attendances,
    sessions_to_dataframe, IST helpers, status classification -- not that
    script's own standalone spot-check CLI mode).

    Depends on the `class_id_lookup` job having already populated
    bronze.class_id_lookup -- see README.md.
    """

    name = "attendance_data.class_session_attendance"
    checkpoint_partition_key = "default"

    def run(self, runtime: JobRuntime, checkpoint: dict[str, Any]) -> None:
        start_ts, end_ts = _date_window()

        lookup_entries = self._load_class_id_lookup()
        already_processed = self._load_already_processed()

        pending = [entry for entry in lookup_entries if entry["class_id"] not in already_processed]

        class_ids_processed = int(checkpoint.get("class_ids_processed", 0))

        for entry in pending:
            class_id = entry["class_id"]
            classes = self._fetch_org_attendances(runtime, class_id, start_ts, end_ts)

            rows: list[tuple[Any, ...]] = []
            if classes:
                sessions = [
                    session
                    for row in classes
                    if (
                        session := _session_from_class_row(row, entry["bundle_id"], entry["bundle_name"])
                    )
                    is not None
                ]
                _assign_session_numbers(sessions)
                rows = [_row_tuple(session) for session in sessions]
            # Empty results (no sessions) for a class_id are expected/normal
            # -- self-paced content can have zero sessions -- counted below,
            # not treated as an error.

            class_ids_processed += 1
            runtime.commit_rows(
                table=TABLE,
                columns=COLUMNS,
                rows=rows,
                unique_columns=UNIQUE_COLUMNS,
                checkpoint={
                    "class_ids_processed": class_ids_processed,
                    "updated_at": utc_iso(),
                },
            )

    def _fetch_org_attendances(
        self, runtime: JobRuntime, class_id: str, start_ts: int, end_ts: int
    ) -> list[dict[str, Any]]:
        """GET /organization/attendances. Direct port of
        fetch_org_attendances() from attendance_crossvalidation.py.

        Edmingle's docs show apikey/orgid as HEADERS for this endpoint
        (unlike the report_type=55 endpoint, which is query-param-only) --
        the original script sent both headers AND query params to cover
        whichever the API actually checks. The shared EdmingleApiClient
        session already attaches `apikey`/`ORGID` headers to every request
        (a lowercase `orgid` header is not reproduced separately since HTTP
        header names are case-insensitive and `ORGID` is already present --
        same reasoning as class_id_lookup's README); org_id/apikey are also
        sent as query params here to reproduce the original's belt-and-
        braces behavior exactly.

        Rate limiting/retries (429/5xx backoff) are handled by the shared
        EdmingleApiClient, superseding the original script's own ~24-calls/
        min limiter and "Try after X minutes" 429 parser -- same
        simplification class_id_lookup already made.
        """
        settings = runtime.client.settings
        payload = runtime.client.get_json(
            ORG_ATTENDANCES_PATH,
            params={
                "org_id": settings.organization_id,
                "apikey": settings.api_key,
                "start": start_ts,
                "end": end_ts,
                "class_id": class_id,
            },
            context=f"organization attendances class_id={class_id}",
        )
        if payload.get("code") != 200:
            LOGGER.warning(
                "organization attendances returned non-200 application code",
                extra={"class_id": class_id, "code": payload.get("code")},
            )
            return []
        classes = payload.get("classes")
        return classes if isinstance(classes, list) else []

    def _load_class_id_lookup(self) -> list[dict[str, Any]]:
        """Reads the list of class_ids to pull attendance for from
        bronze.class_id_lookup -- the class_id_lookup job's output table --
        instead of the original script's class_id_lookup.csv. Read-only
        lookup against an upstream job's table, so it uses its own
        short-lived Database connection rather than JobRuntime's
        write-oriented repositories (same pattern as class_id_lookup's own
        read of bronze.course_catalog, and course_enrollments' read of
        bronze.students).

        Skips rows with no resolved class_id (self-paced/archived content
        with no attendance-trackable subject, mirroring the original
        script's `lookup_df.dropna(subset=["class_id"])`) and dedupes by
        class_id, keeping the first occurrence (mirroring
        `.drop_duplicates(subset=["class_id"])`).
        """
        database = Database(DatabaseSettings.from_environment(), "class_session_attendance-lookup-read")
        try:
            with database.connection() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT DISTINCT class_id, bundle_id, bundle_name
                    FROM bronze.class_id_lookup
                    WHERE class_id IS NOT NULL
                    ORDER BY class_id
                    """
                )
                raw_rows = cursor.fetchall()
        finally:
            database.close()

        seen: set[str] = set()
        entries: list[dict[str, Any]] = []
        for class_id, bundle_id, bundle_name in raw_rows:
            normalized = _id_text(class_id)
            if normalized is None or normalized in seen:
                continue
            seen.add(normalized)
            entries.append({"class_id": normalized, "bundle_id": bundle_id, "bundle_name": bundle_name})
        return entries

    def _load_already_processed(self) -> set[str]:
        """Output-table-based resume, equivalent to
        build_session_attendance.py's load_already_processed(): class_ids
        already present in bronze.class_session_attendance are skipped on
        this and every future run (mirrors class_id_lookup's checkpoint
        pattern against its own output table)."""
        database = Database(DatabaseSettings.from_environment(), "class_session_attendance-checkpoint-read")
        try:
            with database.connection() as connection, connection.cursor() as cursor:
                cursor.execute("SELECT DISTINCT class_id FROM bronze.class_session_attendance")
                rows = cursor.fetchall()
        finally:
            database.close()

        processed: set[str] = set()
        for (value,) in rows:
            normalized = _id_text(value)
            if normalized is not None:
                processed.add(normalized)
        return processed


def _date_window() -> tuple[int, int]:
    """CLASS_SESSION_ATTENDANCE_START_DATE/END_DATE are required (YYYY-MM-DD)
    -- unlike the `attendance` (report_type=55) job, this pipeline has no
    default lookback, matching the original CLI's required --start/--end."""
    start_raw = os.getenv("CLASS_SESSION_ATTENDANCE_START_DATE", "").strip()
    end_raw = os.getenv("CLASS_SESSION_ATTENDANCE_END_DATE", "").strip()
    if not start_raw or not end_raw:
        raise ValueError(
            "CLASS_SESSION_ATTENDANCE_START_DATE and CLASS_SESSION_ATTENDANCE_END_DATE "
            "are required (YYYY-MM-DD)"
        )
    return to_unix(start_raw), to_unix(end_raw)
