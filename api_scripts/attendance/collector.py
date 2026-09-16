from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

from api_scripts.common.edmingle import require_record_list
from api_scripts.common.repositories import utc_iso
from api_scripts.common.runtime import CollectorRuntime

# ═══════════════════════════════════════════════════════════════════
# Ported from the standalone production script `attendance.py`
# (Edmingle report_type=55 attendance pipeline, v1.2.0). That script's
# retry/backoff/circuit-breaker/network-outage-detection machinery is NOT
# reimplemented here -- it already lives in api_scripts.common.api_client.
# EdmingleApiClient.get_json() (per-request retry with backoff + jitter,
# Retry-After handling for 429, fatal-vs-retriable HTTP status handling).
# This file only adds the pandas transform layer the original script had
# on top of its own fetch mechanics: per-session and per-batch attendance
# summaries.
#
# FULL-WINDOW RECOMPUTE, NOT INCREMENTAL: every summary field below
# (session_number, first_class_date, retention_percentage, ...) depends on
# a batch's ENTIRE session history within the requested window, not just
# newly-arrived days. So, unlike the raw-ingestion collector this replaces,
# this collector does NOT resume from a `last_completed_date` checkpoint --
# every run re-fetches and recomputes its full ATTENDANCE_START_DATE /
# ATTENDANCE_END_DATE / ATTENDANCE_LOOKBACK_DAYS window from scratch. The
# original script has the same property: each invocation's summary is
# computed purely from whatever --from/--to range was passed to it, with
# no merge against a previous run's output. See README.md for details.
# ═══════════════════════════════════════════════════════════════════

IST = timezone(timedelta(hours=5, minutes=30), name="IST")

LOGGER = logging.getLogger("warehouse.collector.attendance")

BATCH_SUMMARY_TABLE = "bronze.report55_batch_attendance_summary"
SESSION_TABLE = "bronze.report55_session_attendance"

# Column order here must exactly match the order of values built in
# _batch_summary_rows(). pipeline_run_id / received_at / id / created_at
# are populated by TransformedTableRepository.write_with_checkpoint itself.
BATCH_SUMMARY_COLUMNS = [
    "batch_id",
    "batch_name",
    "bundle_id",
    "bundle_name",
    "course_id",
    "course_name",
    "teacher_id",
    "teacher_name",
    "total_students_enrolled",
    "first_class_date",
    "last_class_date",
    "first_class_attendance",
    "last_class_attendance",
    "total_present_marks",
    "total_absent_marks",
    "attendance_percentage",
    "average_class_attendance",
    "highest_class_attendance",
    "lowest_class_attendance",
    "average_rating",
    "retention_percentage",
    "attendance_drop",
    "summary_window_start",
    "summary_window_end",
]

# bronze.report55_batch_attendance_summary has UNIQUE (batch_id,
# summary_window_start, summary_window_end) -- this is a full-window
# recompute job, so each distinct window an operator runs gets its own row
# per batch, and re-running the SAME window upserts (ON CONFLICT DO UPDATE)
# rather than duplicating.
BATCH_SUMMARY_UNIQUE_COLUMNS = ["batch_id", "summary_window_start", "summary_window_end"]

# Column order here must exactly match the order of values built in
# _session_rows().
SESSION_COLUMNS = [
    "batch_id",
    "batch_name",
    "course_id",
    "course_name",
    "session_number",
    "session_id",
    "class_date",
    "is_session_conducted",
    "present_count",
    "absent_count",
    "late_count",
    "total_marked",
    "session_attendance_percentage",
]

# bronze.report55_session_attendance has UNIQUE (batch_id, session_id) --
# re-running an overlapping window upserts the same (batch, session) row
# rather than duplicating it.
SESSION_UNIQUE_COLUMNS = ["batch_id", "session_id"]

# Session rows are committed in chunks rather than one giant INSERT -- a
# long date range (the original script's own docstring cites 546 days /
# ~150 MB raw output) can produce many thousands of (batch, session) rows.
# Chunking keeps each transaction bounded and means a crash partway through
# the write leaves earlier chunks durably committed (idempotent upsert on
# (batch_id, session_id), so a re-run safely overlaps).
SESSION_COMMIT_CHUNK_SIZE = 2000

DEFAULT_ACTIVE_STATUS_VALUES = ["Active"]
DEFAULT_PRESENT_VALUE = "P"
DEFAULT_ABSENT_VALUE = "A"
DEFAULT_LATE_VALUE = "L"
DEFAULT_SESSION_ID_COLUMN = "attendance_id"

# Statuses counted as "marked" alongside present/absent/late -- excludes the
# "-" not-marked placeholder Edmingle uses for not-yet-taken attendance.
_EXTRA_MARKED_STATUSES = ("E", "OL", "NA")

# classDate / startTime formats as returned by the report_type=55 CSV/JSON
# endpoint. Hardcoded (matching the endpoint's fixed response format)
# rather than made configurable -- the task did not call for new env vars
# here, unlike the original script's config.yaml pipeline.date_format /
# pipeline.time_format.
_CLASS_DATE_FORMAT = "%d %b %Y"
_START_TIME_FORMAT = "%I:%M %p"


class AttendanceCollector:
    name = "attendance"
    checkpoint_partition_key = "daily"

    def run(self, runtime: CollectorRuntime, checkpoint: dict[str, Any]) -> None:
        start_date, end_date = _collection_window()
        if start_date > end_date:
            runtime.last_checkpoint = checkpoint
            return

        raw_frames: list[pd.DataFrame] = _fetch_window(runtime, start_date, end_date)
        window_checkpoint = _window_checkpoint(start_date, end_date)

        if not raw_frames:
            LOGGER.info(
                "attendance: no rows fetched for %s..%s -- committing empty summaries",
                start_date,
                end_date,
            )
            runtime.commit_rows(
                table=SESSION_TABLE,
                columns=SESSION_COLUMNS,
                rows=[],
                unique_columns=SESSION_UNIQUE_COLUMNS,
                checkpoint=window_checkpoint,
                partition_key=self.checkpoint_partition_key,
            )
            runtime.commit_rows(
                table=BATCH_SUMMARY_TABLE,
                columns=BATCH_SUMMARY_COLUMNS,
                rows=[],
                unique_columns=BATCH_SUMMARY_UNIQUE_COLUMNS,
                checkpoint=window_checkpoint,
                partition_key=self.checkpoint_partition_key,
            )
            return

        raw_df = pd.concat(raw_frames, ignore_index=True)

        session_col = _resolve_session_id_column(raw_df)
        clean_df = _clean_data(raw_df, session_col)
        _validate_present_value(clean_df)

        class_summary = _build_class_summary(clean_df, session_col)
        batch_summary = _compute_batch_summary(clean_df, class_summary, session_col)

        session_rows = _session_rows(class_summary, session_col)
        if session_rows:
            for offset in range(0, len(session_rows), SESSION_COMMIT_CHUNK_SIZE):
                chunk = session_rows[offset : offset + SESSION_COMMIT_CHUNK_SIZE]
                runtime.commit_rows(
                    table=SESSION_TABLE,
                    columns=SESSION_COLUMNS,
                    rows=chunk,
                    unique_columns=SESSION_UNIQUE_COLUMNS,
                    checkpoint=window_checkpoint,
                    partition_key=self.checkpoint_partition_key,
                )
        else:
            runtime.commit_rows(
                table=SESSION_TABLE,
                columns=SESSION_COLUMNS,
                rows=[],
                unique_columns=SESSION_UNIQUE_COLUMNS,
                checkpoint=window_checkpoint,
                partition_key=self.checkpoint_partition_key,
            )

        batch_rows = _batch_summary_rows(batch_summary, start_date, end_date)
        runtime.commit_rows(
            table=BATCH_SUMMARY_TABLE,
            columns=BATCH_SUMMARY_COLUMNS,
            rows=batch_rows,
            unique_columns=BATCH_SUMMARY_UNIQUE_COLUMNS,
            checkpoint=window_checkpoint,
            partition_key=self.checkpoint_partition_key,
        )


# ============================================================
# FETCH (one call per IST calendar day, same as the raw-ingestion collector)
# ============================================================

def _fetch_window(runtime: CollectorRuntime, start_date: date, end_date: date) -> list[pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    current = start_date
    while current <= end_date:
        day_start = datetime.combine(current, datetime.min.time(), tzinfo=IST)
        day_end = datetime.combine(current, datetime.max.time().replace(microsecond=0), tzinfo=IST)
        params = {
            "apikey": runtime.client.settings.api_key,
            "ORGID": runtime.client.settings.organization_id,
            "report_type": 55,
            "organization_id": runtime.client.settings.organization_id,
            "start_time": int(day_start.timestamp()),
            "end_time": int(day_end.timestamp()),
            "response_type": 1,
        }
        payload = runtime.client.get_json(
            "/report/csv",
            params=params,
            context=f"attendance date={current.isoformat()}",
        )
        rows = require_record_list(payload, "data", "attendance response")
        if rows:
            frames.append(pd.DataFrame(rows))
        else:
            LOGGER.debug("attendance: 0 rows for %s (quiet day / no sessions)", current.isoformat())
        current += timedelta(days=1)
    return frames


def _collection_window() -> tuple[date, date]:
    """Resolves the date window from ATTENDANCE_START_DATE / ATTENDANCE_END_DATE /
    ATTENDANCE_LOOKBACK_DAYS -- the same env vars and defaults as the raw-ingestion
    collector this replaces. Deliberately does NOT fall back to resuming from a
    checkpoint's last_completed_date: this is a full-window recompute job (see
    module docstring), so the window is always fully operator/env-controlled."""
    yesterday = datetime.now(IST).date() - timedelta(days=1)
    end = _optional_date("ATTENDANCE_END_DATE") or yesterday
    explicit_start = _optional_date("ATTENDANCE_START_DATE")
    if explicit_start:
        start = explicit_start
    else:
        lookback = int(os.getenv("ATTENDANCE_LOOKBACK_DAYS", "1"))
        if lookback < 1 or lookback > 3650:
            raise ValueError("ATTENDANCE_LOOKBACK_DAYS must be between 1 and 3650")
        start = end - timedelta(days=lookback - 1)
    return start, end


def _optional_date(name: str) -> date | None:
    raw = os.getenv(name, "").strip()
    return date.fromisoformat(raw) if raw else None


def _window_checkpoint(start_date: date, end_date: date) -> dict[str, Any]:
    return {
        "summary_window_start": start_date.isoformat(),
        "summary_window_end": end_date.isoformat(),
        "updated_at": utc_iso(),
    }


# ============================================================
# CONFIG (env vars)
# ============================================================

def _active_status_values() -> list[str]:
    raw = os.getenv("ATTENDANCE_ACTIVE_STATUS_VALUES", "Active")
    values = [v.strip() for v in raw.split(",") if v.strip()]
    return values or DEFAULT_ACTIVE_STATUS_VALUES


def _present_value() -> str:
    return os.getenv("ATTENDANCE_PRESENT_VALUE", DEFAULT_PRESENT_VALUE).strip() or DEFAULT_PRESENT_VALUE


def _absent_value() -> str:
    return os.getenv("ATTENDANCE_ABSENT_VALUE", DEFAULT_ABSENT_VALUE).strip() or DEFAULT_ABSENT_VALUE


def _late_value() -> str:
    return os.getenv("ATTENDANCE_LATE_VALUE", DEFAULT_LATE_VALUE).strip() or DEFAULT_LATE_VALUE


def _treat_zero_rating_as_missing() -> bool:
    raw = os.getenv("ATTENDANCE_TREAT_ZERO_RATING_AS_MISSING", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


# ============================================================
# CLEAN + VALIDATE
# ============================================================

def _resolve_session_id_column(df: pd.DataFrame) -> str:
    col = os.getenv("ATTENDANCE_SESSION_ID_COLUMN", DEFAULT_SESSION_ID_COLUMN).strip() or DEFAULT_SESSION_ID_COLUMN
    if col in df.columns:
        return col
    LOGGER.warning(
        "%r not found in attendance response -- falling back to 'class_Id'. "
        "class_Id is a subject/stream, NOT a session. Session counts will be UNDERCOUNTED.",
        col,
    )
    return "class_Id"


def _filter_active_students(df: pd.DataFrame) -> pd.DataFrame:
    """Keep ONLY rows whose studentBatchStatus is in ATTENDANCE_ACTIVE_STATUS_VALUES
    (default: ["Active"]). Uses an allow-list (keep Active) rather than a
    block-list (drop Archived) so any new/unexpected status value Edmingle
    introduces is excluded by default instead of silently counted -- same
    reasoning as the original script's filter_active_students()."""
    if "studentBatchStatus" not in df.columns:
        LOGGER.warning(
            "'studentBatchStatus' column not found in attendance response -- "
            "cannot filter inactive students. All rows kept."
        )
        return df

    active_values = _active_status_values()
    status = df["studentBatchStatus"].astype(str).str.strip()
    keep_mask = status.isin(active_values)

    dropped = int((~keep_mask).sum())
    if dropped:
        LOGGER.info(
            "attendance: student status filter keeping only %s -- dropped %d/%d row(s)",
            active_values,
            dropped,
            len(df),
        )
    return df[keep_mask]


def _clean_data(df: pd.DataFrame, session_col: str) -> pd.DataFrame:
    df = df.copy()

    df["classDate"] = pd.to_datetime(df["classDate"], format=_CLASS_DATE_FORMAT, errors="coerce")
    bad = int(df["classDate"].isna().sum())
    if bad:
        LOGGER.warning("attendance: dropping %d row(s) with unparseable classDate", bad)
    df = df.dropna(subset=["classDate"])

    before = len(df)
    df = df.drop_duplicates()
    removed = before - len(df)
    if removed:
        LOGGER.info("attendance: removed %d exact duplicate row(s)", removed)

    key_cols = ["batch_Id", "student_Id", session_col]
    missing = df[key_cols].isna().any(axis=1)
    if missing.any():
        LOGGER.warning("attendance: dropping %d row(s) missing key columns", int(missing.sum()))
        df = df[~missing]

    conflict = df.groupby(["student_Id", session_col]).size()
    n_conflict = int((conflict > 1).sum())
    if n_conflict:
        LOGGER.warning(
            "attendance: %d (student_Id, %s) pair(s) have >1 row after dedup -- "
            "not auto-resolved, all rows kept",
            n_conflict,
            session_col,
        )

    # ── ACTIVE-ONLY FILTER: drop Archived / non-active students ──────────
    df = _filter_active_students(df)

    start_parsed = pd.to_datetime(df["startTime"], format=_START_TIME_FORMAT, errors="coerce")
    seconds = start_parsed.dt.hour.fillna(0) * 3600 + start_parsed.dt.minute.fillna(0) * 60
    df["_class_datetime"] = df["classDate"] + pd.to_timedelta(seconds, unit="s")

    LOGGER.info("attendance: clean complete, %d row(s) ready for summarisation", len(df))
    return df.reset_index(drop=True)


def _validate_present_value(df: pd.DataFrame) -> None:
    """Data-sanity guard from the original script: if the configured 'present'
    value never appears in studentAttendanceStatus, every attendance metric
    computed below would silently be zero."""
    present_value = _present_value()
    observed = sorted(df["studentAttendanceStatus"].dropna().unique().tolist())
    if present_value not in observed:
        raise ValueError(
            f"ATTENDANCE_PRESENT_VALUE={present_value!r} not found in studentAttendanceStatus. "
            f"Observed: {observed}. Every attendance metric would be 0. "
            f"Fix ATTENDANCE_PRESENT_VALUE."
        )


# ============================================================
# SUMMARY COMPUTATION
# ============================================================

def _build_class_summary(df: pd.DataFrame, session_col: str) -> pd.DataFrame:
    today = pd.Timestamp(datetime.now(IST).date())
    pv, av, lv = _present_value(), _absent_value(), _late_value()
    df = df.copy()

    df["_present_student"] = df["student_Id"].where(df["studentAttendanceStatus"] == pv)
    df["_absent_student"] = df["student_Id"].where(df["studentAttendanceStatus"] == av)
    df["_late_student"] = df["student_Id"].where(df["studentAttendanceStatus"] == lv)
    # "marked" = any real status (excludes the "-" not-marked placeholder)
    df["_marked_student"] = df["student_Id"].where(
        df["studentAttendanceStatus"].isin([pv, av, lv, *_EXTRA_MARKED_STATUSES])
    )

    cs = (
        df.groupby(["batch_Id", session_col])
        .agg(
            classDate=("classDate", "first"),
            _class_datetime=("_class_datetime", "min"),
            batchName=("batchName", "first"),
            course_Id=("course_Id", "first"),
            courseName=("courseName", "first"),
            present_count=("_present_student", "nunique"),
            absent_count=("_absent_student", "nunique"),
            late_count=("_late_student", "nunique"),
            total_marked=("_marked_student", "nunique"),
        )
        .reset_index()
    )
    cs["is_conducted"] = cs["classDate"] <= today
    cs = cs.sort_values(["batch_Id", "_class_datetime", session_col]).reset_index(drop=True)
    cs["session_number"] = cs.groupby("batch_Id").cumcount() + 1

    # present_count / total_marked * 100, NULL (not 0) when total_marked is
    # 0 -- matches the original script's div-by-zero-safe convention (a
    # session with nothing marked has an unknown percentage, not a 0% one).
    total_marked = cs["total_marked"].astype("Float64")
    pct = (cs["present_count"].astype("Float64") / total_marked.replace(0, np.nan) * 100).round(2)
    cs["session_attendance_percentage"] = pct

    return cs


def _compute_batch_summary(df: pd.DataFrame, cs: pd.DataFrame, session_col: str) -> pd.DataFrame:
    conducted = cs[cs["is_conducted"]]

    basic = ["batchName", "bundle_Id", "bundleName", "course_Id", "courseName", "teacher_Id", "teacherName"]
    summary = df.groupby("batch_Id")[basic].first()

    summary["total_students_enrolled"] = df.groupby("batch_Id")["student_Id"].nunique()

    # total_classes_planned / conducted / remaining are computed here (as the
    # original script does) but -- matching the original's own OUTPUT_COLUMNS,
    # which also drops them -- are not part of bronze.report55_batch_attendance_summary's
    # confirmed schema and so are not persisted below.
    total_classes_planned = cs.groupby("batch_Id")[session_col].nunique()
    total_classes_conducted = (
        conducted.groupby("batch_Id")[session_col].nunique().reindex(summary.index, fill_value=0)
    )
    _ = (total_classes_planned - total_classes_conducted).clip(lower=0)  # total_classes_remaining (not persisted)

    summary["total_present_marks"] = (
        conducted.groupby("batch_Id")["present_count"].sum().reindex(summary.index, fill_value=0)
    )
    summary["total_absent_marks"] = (
        conducted.groupby("batch_Id")["absent_count"].sum().reindex(summary.index, fill_value=0)
    )

    summary["first_class_date"] = cs.groupby("batch_Id")["classDate"].min()
    summary["last_class_date"] = conducted.groupby("batch_Id")["classDate"].max().reindex(summary.index)

    summary["first_class_attendance"] = (
        cs.groupby("batch_Id").first()["present_count"].reindex(summary.index, fill_value=0)
    )

    last_attendance = conducted.groupby("batch_Id").last()["present_count"].reindex(summary.index)
    summary["last_class_attendance"] = last_attendance
    has_conducted = summary["last_class_date"].notna()
    summary.loc[has_conducted & summary["last_class_attendance"].isna(), "last_class_attendance"] = 0

    avg_present = cs.groupby("batch_Id")["present_count"].mean()
    summary["attendance_percentage"] = (avg_present / summary["total_students_enrolled"] * 100).round(2)

    conducted_present = conducted.groupby("batch_Id")["present_count"]
    summary["average_class_attendance"] = conducted_present.mean().round(2).reindex(summary.index)
    summary["highest_class_attendance"] = conducted_present.max().reindex(summary.index)
    summary["lowest_class_attendance"] = conducted_present.min().reindex(summary.index)

    rating = pd.to_numeric(df["studentRating"], errors="coerce")
    if _treat_zero_rating_as_missing():
        # studentRating is EXACTLY 0 in the overwhelming majority of real
        # rows -- Edmingle's "not rated" sentinel -- so it is excluded from
        # the mean by default.
        rating = rating.replace(0, np.nan)
    df = df.copy()
    df["_rating"] = rating
    summary["average_rating"] = df.groupby("batch_Id")["_rating"].mean().round(2)

    summary["retention_percentage"] = (
        (summary["last_class_attendance"] / summary["first_class_attendance"] * 100)
        .replace([np.inf, -np.inf], np.nan)
        .round(2)
    )
    summary["attendance_drop"] = summary["first_class_attendance"] - summary["last_class_attendance"]

    return summary.reset_index()


# ============================================================
# ROW BUILDERS (DataFrame -> commit_rows() tuples)
# ============================================================

def _scalar(value: Any) -> Any:
    """Converts a pandas/numpy scalar to a plain Python value for psycopg2,
    mapping NaN / NaT / pd.NA to None and pd.Timestamp to date()."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def _text(value: Any) -> str | None:
    value = _scalar(value)
    return None if value is None else str(value)


def _session_rows(cs: pd.DataFrame, session_col: str) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for record in cs.to_dict("records"):
        rows.append(
            (
                _text(record["batch_Id"]),
                _text(record["batchName"]),
                _text(record["course_Id"]),
                _text(record["courseName"]),
                _scalar(record["session_number"]),
                _text(record[session_col]),
                _scalar(record["classDate"]),
                bool(record["is_conducted"]),
                _scalar(record["present_count"]),
                _scalar(record["absent_count"]),
                _scalar(record["late_count"]),
                _scalar(record["total_marked"]),
                _scalar(record["session_attendance_percentage"]),
            )
        )
    return rows


def _batch_summary_rows(summary: pd.DataFrame, start_date: date, end_date: date) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for record in summary.to_dict("records"):
        rows.append(
            (
                _text(record["batch_Id"]),
                _text(record["batchName"]),
                _text(record["bundle_Id"]),
                _text(record["bundleName"]),
                _text(record["course_Id"]),
                _text(record["courseName"]),
                _text(record["teacher_Id"]),
                _text(record["teacherName"]),
                _scalar(record["total_students_enrolled"]),
                _scalar(record["first_class_date"]),
                _scalar(record["last_class_date"]),
                _scalar(record["first_class_attendance"]),
                _scalar(record["last_class_attendance"]),
                _scalar(record["total_present_marks"]),
                _scalar(record["total_absent_marks"]),
                _scalar(record["attendance_percentage"]),
                _scalar(record["average_class_attendance"]),
                _scalar(record["highest_class_attendance"]),
                _scalar(record["lowest_class_attendance"]),
                _scalar(record["average_rating"]),
                _scalar(record["retention_percentage"]),
                _scalar(record["attendance_drop"]),
                start_date,
                end_date,
            )
        )
    return rows
