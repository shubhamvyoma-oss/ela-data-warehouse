from __future__ import annotations

import hashlib
import json
from typing import Any

import pandas as pd
from psycopg2.extras import Json

from api_scripts.common.repositories import utc_iso
from api_scripts.common.runtime import CollectorRuntime


class CourseCatalogueRawCollector:
    """Ported unchanged from corses-batches/course_catalogue_data (1).py: a single,
    unretried GET against the institute catalogue endpoint, then a generic
    recursive-list-finder + pandas.json_normalize flatten producing dynamic,
    unknown-ahead-of-time columns. Only the sink changed (CSV -> Postgres);
    see bronze.course_catalogue_raw and this folder's README for details.
    """

    name = "corses_batches.course_catalogue_raw"
    checkpoint_partition_key = "default"

    def run(self, runtime: CollectorRuntime, checkpoint: dict[str, Any]) -> None:
        institute_id = runtime.client.settings.institute_id
        if not institute_id:
            raise ValueError("EDMINGLE_INSTITUTE_ID is required for course_catalogue_raw")

        payload = runtime.client.get_json(
            f"/institute/{institute_id}/courses/catalogue",
            params={"institution_id": institute_id},
            context="course catalogue raw",
        )

        records = _find_first_list_of_dicts(payload)
        flattened = pd.json_normalize(records if records is not None else payload)

        rows: list[tuple[Any, ...]] = []
        for row in flattened.to_dict(orient="records"):
            row_json = json.dumps(row, sort_keys=True, default=str)
            row_sha256 = hashlib.sha256(row_json.encode("utf-8")).hexdigest()
            bundle_id = _extract_bundle_id(row)
            # Reuse the same canonical (sorted, default=str) serialization for the
            # stored payload so raw_payload and row_sha256 are always consistent,
            # and so pandas/numpy scalar types (e.g. numpy.int64) that plain
            # json.dumps can't handle don't blow up the insert.
            rows.append((bundle_id, row_sha256, Json(row, dumps=lambda _v, s=row_json: s)))

        runtime.commit_rows(
            table="bronze.course_catalogue_raw",
            columns=["bundle_id", "row_sha256", "raw_payload"],
            rows=rows,
            unique_columns=["bundle_id", "row_sha256"],
            checkpoint={"completed_at": utc_iso(), "row_count": len(rows)},
        )


def _find_first_list_of_dicts(obj: Any) -> list[dict[str, Any]] | None:
    """Recursively search for the first list of dicts in a nested JSON object.

    Ported unchanged from corses-batches/course_catalogue_data (1).py's
    find_first_list_of_dicts.
    """
    if isinstance(obj, list) and all(isinstance(item, dict) for item in obj):
        return obj
    if isinstance(obj, dict):
        for value in obj.values():
            result = _find_first_list_of_dicts(value)
            if result is not None:
                return result
    return None


def _extract_bundle_id(row: dict[str, Any]) -> Any:
    """Best-effort identity extraction from the flattened row.

    Checks common keys in a fixed priority order; returns the first present,
    non-null value, else None. This is intentionally the only extraction rule
    -- no other heuristics are applied.
    """
    for key in ("Bundle id", "bundle_id", "_id", "id"):
        value = row.get(key)
        if value is not None:
            return value
    return None
