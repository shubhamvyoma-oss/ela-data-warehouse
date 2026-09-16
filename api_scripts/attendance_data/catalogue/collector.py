from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from api_scripts.common.api_client import ApiContractError
from api_scripts.common.edmingle import require_record_list
from api_scripts.common.repositories import utc_iso
from api_scripts.common.runtime import CollectorRuntime

# ═══════════════════════════════════════════════════════════════════
# This collector is a line-for-line port of the legacy standalone script
# `build_course_catalog.py` (the PRIMARY catalogue builder -- there is a
# non-primary backup, `build_course_catalog_alt.py`, which this does NOT
# port) onto Postgres via CollectorRuntime.commit_rows(). Only the output
# sink changed -- CSV became bronze.course_catalog -- every extract/filter/
# derive rule below is preserved exactly, including the quirks noted
# inline. Do not "fix" or simplify the business logic here without
# checking the original script first.
# ═══════════════════════════════════════════════════════════════════

# Unlike the sibling `course_batch_merge` job (which fetches all three
# masterbatch statuses, including Archived, because its own source script
# needs the full batch history), THIS job's source script only ever fetches
# Active and Completed. Archived is intentionally never fetched here -- do
# not add status=1.
_BATCH_STATUSES: dict[int, str] = {0: "Active", 3: "Completed"}

# The original script hardcodes per_page=1000. Preserved as-is.
_BATCHES_PER_PAGE = 1000

# Specific batch_id values to exclude outright. Nothing here is matched by
# name -- only by this exact ID list, applied before any other transform
# (bundle-enrollment rollup, latest-batch marking, etc. all see the batch
# universe with these IDs already removed). Ported verbatim from
# build_course_catalog.py's BATCH_IDS_TO_EXCLUDE.
_BATCH_IDS_TO_EXCLUDE: set[int] = {
    12458, 12459, 12464, 12472, 12473, 12474, 12475, 12485, 12487,
    12513, 12522, 12550, 12551, 12554, 12606, 12607,
    70572, 42632, 70587, 53438,
}

_VALID_CATALOGUE_STATUSES = {"Completed", "Ongoing", "Upcoming"}

# batch-specific fields nulled out on synthetic "catalogue-only" rows
_BATCH_ONLY_COLUMNS = [
    "batch_id",
    "batch_name",
    "batch_status",
    "start_date",
    "end_date",
    "tutor_name",
    "tutor_id",
    "batch_enrollment_count",
]


class CourseCatalogueCollector:
    """Ported from build_course_catalog.py (the primary Stage-1 catalogue
    builder). Full-refresh: fetches the whole catalogue + Active/Completed
    batches every run and writes the merged result straight into
    bronze.course_catalog (a dedicated, already-transformed Bronze table --
    see TransformedTableRepository), matching the original script's
    behavior of regenerating the entire CSV from scratch each run."""

    name = "attendance_data.catalogue"
    checkpoint_partition_key = "default"

    def run(self, runtime: CollectorRuntime, checkpoint: dict[str, Any]) -> None:
        institute_id = runtime.client.settings.institute_id
        if not institute_id:
            raise ValueError("EDMINGLE_INSTITUTE_ID is required for catalogue")
        organization_id = runtime.client.settings.organization_id

        # ── Step 1: Fetch data ──────────────────────────────────────
        cat_df = _fetch_catalogue(runtime, institute_id)
        batch_df = _fetch_batches(runtime, organization_id)

        # ── Step 2: Exclude specific known-bad batch IDs ────────────
        batch_df = _filter_excluded_batches(batch_df)

        # ── Step 3: Compute bundle_enrollment_count before merge ────
        batch_df = _compute_bundle_enrollment(batch_df)

        # ── Step 4: Mark Is_Latest_Batch ────────────────────────────
        batch_df = _mark_latest_batch(batch_df)

        # ── Step 5: Mark Has_Batch ──────────────────────────────────
        batch_df["Has_Batch"] = 1

        # ── Step 6: Merge catalogue into batch rows ─────────────────
        merged = batch_df.merge(cat_df, left_on="bundle_id", right_on="Bundle id", how="left")
        merged["Catalogue_Match"] = merged["Bundle id"].notna().astype(int)

        # ── Step 7: Apply business logic (Final_Status) ─────────────
        merged = _apply_business_logic(merged)

        # ── Step 8: Add catalogue-only courses (no batches) ─────────
        final_df = _add_courses_without_batches(merged, cat_df)

        # ── Step 9: Format dates (Unix timestamp -> date) ───────────
        final_df = _format_dates(final_df)

        # ── Step 10: Build rows + write to Postgres ──────────────────
        rows = _build_rows(final_df)
        runtime.commit_rows(
            table="bronze.course_catalog",
            columns=[target for target, _source, _caster in _FIELD_MAP],
            rows=rows,
            unique_columns=["batch_id", "bundle_id"],
            checkpoint={"completed_at": utc_iso(), "row_count": len(rows)},
            partition_key=self.checkpoint_partition_key,
        )


# ── Fetch: catalogue ─────────────────────────────────────────────────
def _fetch_catalogue(runtime: CollectorRuntime, institute_id: str) -> pd.DataFrame:
    payload = runtime.client.get_json(
        f"/institute/{institute_id}/courses/catalogue",
        params={"institution_id": institute_id},
        context="course catalogue",
    )
    rows = require_record_list(payload, "response", "course catalogue response")
    if not rows:
        # Mirrors the original script's "Catalogue fetch failed. Aborting."
        raise ApiContractError("course catalogue fetch returned no rows; aborting full refresh")
    return pd.DataFrame(rows)


# ── Fetch: batches (Active + Completed only, paginated) ─────────────
def _fetch_batches(runtime: CollectorRuntime, organization_id: str) -> pd.DataFrame:
    all_rows: list[dict[str, Any]] = []

    for status_code, status_label in _BATCH_STATUSES.items():
        page = 1
        while True:
            payload = runtime.client.get_json(
                "/short/masterbatch",
                params={
                    "status": status_code,
                    "page": page,
                    "per_page": _BATCHES_PER_PAGE,
                    "organization_id": organization_id,
                },
                context=f"course catalogue batches status={status_code} page={page}",
            )
            courses = require_record_list(payload, "courses", "course catalogue batches response")

            if not courses:
                break

            for course in courses:
                bundle_id = course.get("bundle_id")
                bundle_name = str(course.get("bundle_name", "")).strip()
                # Default matches the source script exactly: a course with no
                # "batch" key still produces one placeholder row.
                batches = course.get("batch", [{}])
                for b in batches:
                    all_rows.append(
                        {
                            "bundle_id": bundle_id,
                            "bundle_name": bundle_name,
                            "batch_id": b.get("class_id"),
                            "batch_name": str(b.get("class_name", "")).strip(),
                            "batch_status": status_label,
                            "start_date": b.get("start_date"),
                            "end_date": b.get("end_date"),
                            "tutor_name": b.get("tutor_name"),
                            "tutor_id": b.get("tutor_id"),
                            "batch_enrollment_count": b.get("admitted_students", 0) or 0,
                        }
                    )

            # Pagination: stop when fewer rows than per_page were returned.
            if len(courses) < _BATCHES_PER_PAGE:
                break
            page += 1

    if not all_rows:
        # Mirrors the original script's "Batch fetch returned no data. Aborting."
        raise ApiContractError("course catalogue batches fetch returned no rows; aborting full refresh")
    return pd.DataFrame(all_rows)


# ── Transform steps (ported 1:1 from the legacy script) ─────────────
def _is_excluded_batch_id(batch_id: Any) -> bool:
    try:
        return int(batch_id) in _BATCH_IDS_TO_EXCLUDE
    except (TypeError, ValueError):
        return False


def _filter_excluded_batches(df: pd.DataFrame) -> pd.DataFrame:
    """Drops rows whose batch_id is in _BATCH_IDS_TO_EXCLUDE. Applied before
    any other transform, exactly like build_course_catalog.py's
    filter_excluded_batches()."""
    keep_mask = ~df["batch_id"].apply(_is_excluded_batch_id)
    return df.loc[keep_mask].reset_index(drop=True)


def _compute_bundle_enrollment(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["bundle_enrollment_count"] = df.groupby("bundle_id")["batch_enrollment_count"].transform("sum")
    return df


def _mark_latest_batch(df: pd.DataFrame) -> pd.DataFrame:
    working = df.copy()
    working["_sort_date"] = pd.to_numeric(working["start_date"], errors="coerce").fillna(0)
    working = working.sort_values(
        ["bundle_id", "_sort_date", "batch_id"], ascending=[True, False, False]
    ).reset_index(drop=True)

    working["Is_Latest_Batch"] = 0
    is_new_bundle = working["bundle_id"] != working["bundle_id"].shift(1)
    working.loc[is_new_bundle, "Is_Latest_Batch"] = 1

    return working.drop(columns=["_sort_date"])


def _apply_business_logic(df: pd.DataFrame) -> pd.DataFrame:
    working = df.copy()

    # Catalogue_Status mirrors the raw catalogue Status column.
    working["Catalogue_Status"] = working["Status"]

    # Default: all non-latest batches are Completed.
    working["Final_Status"] = "Completed"

    raw_status = working["Status"].astype(str).str.strip()
    is_latest = working["Is_Latest_Batch"] == 1
    valid_mask = is_latest & raw_status.isin(_VALID_CATALOGUE_STATUSES)
    blank_mask = is_latest & ~raw_status.isin(_VALID_CATALOGUE_STATUSES)

    # Latest batch uses the catalogue Status as its Final_Status.
    working.loc[valid_mask, "Final_Status"] = raw_status[valid_mask]
    # Latest batch but no catalogue match (or unrecognized status) -> blank.
    working.loc[blank_mask, "Final_Status"] = ""

    return working


def _add_courses_without_batches(merged_df: pd.DataFrame, cat_df: pd.DataFrame) -> pd.DataFrame:
    existing_ids = set(merged_df["bundle_id"].unique())
    missing_mask = ~cat_df["Bundle id"].isin(existing_ids)
    missing = cat_df.loc[missing_mask].copy().reset_index(drop=True)

    if missing.empty:
        return merged_df

    missing["bundle_id"] = missing["Bundle id"]
    missing["bundle_name"] = missing.get("Course Name", pd.Series(dtype=str))

    missing["Has_Batch"] = 0
    missing["Is_Latest_Batch"] = 1
    missing["bundle_enrollment_count"] = 0
    missing["Catalogue_Match"] = 1  # These came from catalogue so they matched.
    missing["Catalogue_Status"] = missing["Status"]
    missing["Final_Status"] = missing["Status"]

    for col in _BATCH_ONLY_COLUMNS:
        missing[col] = None

    return pd.concat([merged_df, missing], ignore_index=True)


def _format_dates(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["start_date"] = pd.to_datetime(
        pd.to_numeric(df["start_date"], errors="coerce"), unit="s", errors="coerce"
    ).dt.date
    df["end_date"] = pd.to_datetime(
        pd.to_numeric(df["end_date"], errors="coerce"), unit="s", errors="coerce"
    ).dt.date
    return df


# ── Row builders / type casters for the Postgres sink ────────────────
def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return str(value)


def _clean_numeric(value: Any) -> int | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return int(value)


def _clean_bool(value: Any) -> bool | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return bool(int(value))


def _clean_date(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


# (target Postgres column, source DataFrame column, caster) -- order here
# defines both the INSERT column order and the row-tuple order.
_FIELD_MAP: list[tuple[str, str, Callable[[Any], Any]]] = [
    ("bundle_id", "bundle_id", _clean_text),
    ("bundle_name", "bundle_name", _clean_text),
    ("batch_id", "batch_id", _clean_text),
    ("batch_name", "batch_name", _clean_text),
    ("batch_status", "batch_status", _clean_text),
    ("start_date", "start_date", _clean_date),
    ("end_date", "end_date", _clean_date),
    ("tutor_name", "tutor_name", _clean_text),
    ("tutor_id", "tutor_id", _clean_text),
    ("batch_enrollment_count", "batch_enrollment_count", _clean_numeric),
    ("course_name", "Course Name", _clean_text),
    ("tutors", "Tutors", _clean_text),
    ("tutor_ids", "Tutord Ids", _clean_text),  # "Tutord" typo is in the source API/script.
    ("course_ids", "Course Ids", _clean_text),
    ("subject", "Subject", _clean_text),
    ("level", "Level", _clean_text),
    ("language", "Language", _clean_text),
    ("examination", "Examination", _clean_text),
    ("course_type", "Type", _clean_text),
    ("course_division", "Course Division", _clean_text),
    ("certificate", "Certificate", _clean_text),
    ("course_sponsor", "Course Sponsor", _clean_text),
    ("course_title_sanskrit", "Course Title Sanskrit", _clean_text),
    ("catalogue_raw_status", "Status", _clean_text),
    ("number_of_lectures", "Number of Lectures", _clean_text),
    ("duration", "Duration", _clean_text),
    ("personas", "Personas", _clean_text),
    ("computer_based_assessment", "Computer Based Assessment", _clean_text),
    ("product_id", "Product ID", _clean_text),
    ("sss_category", "SSS Category", _clean_text),
    ("viniyoga", "Viniyoga", _clean_text),
    ("adhyayanam_category", "Adhyayanam Category", _clean_text),
    ("term_of_course", "Term of Course", _clean_text),
    ("position_in_funnel", "Position in Funnel", _clean_text),
    ("division", "Division", _clean_text),
    ("is_catalogue_match", "Catalogue_Match", _clean_bool),
    ("bundle_enrollment_count", "bundle_enrollment_count", _clean_numeric),
    ("is_latest_batch", "Is_Latest_Batch", _clean_bool),
    ("has_batch", "Has_Batch", _clean_bool),
    ("catalogue_status", "Catalogue_Status", _clean_text),
    ("final_status", "Final_Status", _clean_text),
]


def _build_rows(df: pd.DataFrame) -> list[tuple[Any, ...]]:
    records = df.to_dict("records")
    return [
        tuple(caster(record.get(source)) for _target, source, caster in _FIELD_MAP)
        for record in records
    ]
