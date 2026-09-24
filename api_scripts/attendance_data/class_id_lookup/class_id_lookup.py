from __future__ import annotations

from typing import Any

from api_scripts.common.repositories import utc_iso
from api_scripts.common.runtime import JobRuntime
from shared.config import DatabaseSettings
from shared.database import Database

TABLE = "bronze.class_id_lookup"

# Matches the OUTPUT_COLUMNS order from resolve_class_ids.py, minus the
# pipeline_run_id/received_at columns that TransformedTableRepository adds
# automatically.
COLUMNS = [
    "bundle_id",
    "bundle_name",
    "batch_id",
    "batch_name",
    "class_id",
    "tutor_name",
    "tutor_id",
    "total_classes",
    "completed_classes",
    "cancelled_classes",
    "num_users",
    "associated_masterbatches",
]

# Matches bronze.class_id_lookup's UNIQUE (batch_id, class_id) constraint.
UNIQUE_COLUMNS = ["batch_id", "class_id"]


def _normalize_batch_id(value: Any) -> str | None:
    """bronze.course_catalog.batch_id is a free-form text column. Normalize
    numeric-looking values (e.g. "12345.0", coming from a pandas float column
    upstream) to a canonical integer string, so the value used in the API URL
    and in the checkpoint/dedup comparisons is stable. Non-numeric values are
    passed through unchanged rather than dropped."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return str(int(float(text)))
    except (TypeError, ValueError):
        return text


def _courses_array_to_records(courses_array: list[Any]) -> list[dict[str, Any]]:
    """Direct port of resolve_class_ids.py's courses_array_to_records(). The
    real courses_array items are already dicts holding the true per-subject
    class_id (courses_array is nested under a `masterbatch` response whose
    own top-level "class_id" is actually the batch id -- misleading naming
    confirmed against the live API, not Edmingle's docs). associated_
    masterbatches is a list; joined to a comma string exactly like the CSV
    version did (relevant to cross-batch broadcast session detection -- one
    class_id can span multiple batches)."""
    records: list[dict[str, Any]] = []
    for item in courses_array:
        if not isinstance(item, dict):
            continue
        assoc = item.get("associated_masterbatches")
        assoc_str = ",".join(str(x) for x in assoc) if isinstance(assoc, list) else assoc
        records.append(
            {
                "class_id": item.get("class_id"),
                "tutor_name": item.get("tutor_name"),
                "tutor_id": item.get("tutor_id"),
                "total_classes": item.get("total_classes"),
                "completed_classes": item.get("completed"),
                "cancelled_classes": item.get("cancelled"),
                "num_users": item.get("num_users"),
                "associated_masterbatches": assoc_str,
            }
        )
    return records


class ClassIdLookupJob:
    """Resolves class_id(s) for every batch_id found in bronze.course_catalog
    via GET /masterbatch/<batch_id>, direct port of
    'Attendance data/resolve_class_ids.py' (Stage 2 of the legacy pipeline).

    Depends on the `catalogue` job having already populated
    bronze.course_catalog -- see README.md.
    """

    name = "attendance_data.class_id_lookup"
    checkpoint_partition_key = "default"

    def run(self, runtime: JobRuntime, checkpoint: dict[str, Any]) -> None:
        catalogue_batches = self._load_catalogue_batches()
        already_processed = self._load_already_processed()

        pending = [
            entry for entry in catalogue_batches if entry["batch_id"] not in already_processed
        ]

        batches_processed = int(checkpoint.get("batches_processed", 0))

        for entry in pending:
            batch_id = entry["batch_id"]
            courses_array = self._fetch_classes_for_batch(runtime, batch_id)
            class_records = _courses_array_to_records(courses_array)

            if not class_records:
                # Still emit one row so a batch resolving to zero classes is
                # never silently dropped -- matches resolve_class_ids.py's
                # `class_records = [{}]` fallback exactly.
                class_records = [{}]

            rows: list[tuple[Any, ...]] = [
                (
                    entry["bundle_id"],
                    entry["bundle_name"],
                    batch_id,
                    entry["batch_name"],
                    record.get("class_id"),
                    record.get("tutor_name"),
                    record.get("tutor_id"),
                    record.get("total_classes"),
                    record.get("completed_classes"),
                    record.get("cancelled_classes"),
                    record.get("num_users"),
                    record.get("associated_masterbatches"),
                )
                for record in class_records
            ]

            batches_processed += 1
            runtime.commit_rows(
                table=TABLE,
                columns=COLUMNS,
                rows=rows,
                unique_columns=UNIQUE_COLUMNS,
                checkpoint={
                    "batches_processed": batches_processed,
                    "updated_at": utc_iso(),
                },
            )

    def _fetch_classes_for_batch(
        self, runtime: JobRuntime, batch_id: str
    ) -> list[Any]:
        """GET /masterbatch/<batch_id>. The shared EdmingleApiClient session
        already sends `apikey` and `ORGID` headers on every request; the
        original script additionally sent apikey/org_id as query params (and
        a lowercase `orgid` header, redundant with `ORGID` since HTTP header
        names are case-insensitive) -- replicated here by passing apikey and
        org_id as params too, so both the header-based and query-param-based
        auth paths the original relied on are preserved.

        Response shape (confirmed live, contradicts Edmingle's own docs):
        {"code": 200, "class": {"courses_array": [...], "class_id": <this is
        actually the BATCH id, not a real class_id>}}. The real per-subject
        class_id values are nested inside class.courses_array[].
        """
        settings = runtime.client.settings
        payload = runtime.client.get_json(
            f"/masterbatch/{batch_id}",
            params={"apikey": settings.api_key, "org_id": settings.organization_id},
            context=f"masterbatch batch_id={batch_id}",
        )
        class_obj = payload.get("class")
        if not isinstance(class_obj, dict):
            return []
        courses_array = class_obj.get("courses_array")
        return courses_array if isinstance(courses_array, list) else []

    def _load_catalogue_batches(self) -> list[dict[str, Any]]:
        """Reads the input list of batches from bronze.course_catalog --
        the ported `catalogue` job's output table -- instead of the original
        script's course_catalog.csv. This is a read-only lookup query against
        an upstream job's table, so it uses its own short-lived Database
        connection rather than JobRuntime's write-oriented repositories.

        Queries DISTINCT (batch_id, bundle_id, bundle_name, batch_name)
        tuples with batch_id IS NOT NULL, per the ported job's spec. A given
        batch_id can appear under more than one bundle context in the
        catalogue; like the original script's
        `drop_duplicates(subset=["batch_id"], keep="first")`, only the first
        (lowest batch_id, then row order) occurrence per batch_id is kept, so
        each batch_id is only ever looked up once per run.
        """
        database = Database(DatabaseSettings.from_environment(), "class_id_lookup-catalogue-read")
        try:
            with database.connection() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT DISTINCT batch_id, bundle_id, bundle_name, batch_name
                    FROM bronze.course_catalog
                    WHERE batch_id IS NOT NULL
                    ORDER BY batch_id
                    """
                )
                raw_rows = cursor.fetchall()
        finally:
            database.close()

        seen: set[str] = set()
        entries: list[dict[str, Any]] = []
        for batch_id, bundle_id, bundle_name, batch_name in raw_rows:
            normalized = _normalize_batch_id(batch_id)
            if normalized is None or normalized in seen:
                continue
            seen.add(normalized)
            entries.append(
                {
                    "batch_id": normalized,
                    "bundle_id": bundle_id,
                    "bundle_name": bundle_name,
                    "batch_name": batch_name,
                }
            )
        return entries

    def _load_already_processed(self) -> set[str]:
        """Output-table-based resume, equivalent to resolve_class_ids.py's
        load_already_processed(): batch_ids already present in
        bronze.class_id_lookup are skipped on this and every future run."""
        database = Database(DatabaseSettings.from_environment(), "class_id_lookup-checkpoint-read")
        try:
            with database.connection() as connection, connection.cursor() as cursor:
                cursor.execute("SELECT DISTINCT batch_id FROM bronze.class_id_lookup")
                rows = cursor.fetchall()
        finally:
            database.close()

        processed: set[str] = set()
        for (value,) in rows:
            normalized = _normalize_batch_id(value)
            if normalized is not None:
                processed.add(normalized)
        return processed
