from __future__ import annotations

from typing import Any

from api_scripts.common.edmingle import (
    BATCH_STATUSES,
    flatten_master_batches,
    has_more_pages,
    require_record_list,
)
from api_scripts.common.models import RawRecord
from api_scripts.common.repositories import utc_iso
from api_scripts.common.runtime import CollectorRuntime


class MasterBatchCollector:
    name = "master_batches"

    def run(self, runtime: CollectorRuntime, checkpoint: dict[str, Any]) -> None:
        if checkpoint.get("in_progress"):
            status_index = int(checkpoint.get("status_index", 0))
            page = int(checkpoint.get("next_page", 1))
        else:
            status_index = 0
            page = 1

        for index in range(status_index, len(BATCH_STATUSES)):
            status = BATCH_STATUSES[index]
            current_page = page if index == status_index else 1
            while True:
                payload = runtime.client.get_json(
                    "/short/masterbatch",
                    params={
                        "status": status,
                        "page": current_page,
                        "per_page": 100,
                        "organization_id": runtime.client.settings.organization_id,
                    },
                    context=f"master_batches status={status} page={current_page}",
                )
                courses = require_record_list(payload, "courses", "master batch response")
                flattened = flatten_master_batches(courses, status)
                records = [
                    RawRecord(
                        resource="master_batches",
                        record_key=key,
                        payload=batch,
                        request_context=context,
                    )
                    for batch, context, key in flattened
                ]
                more = has_more_pages(payload)
                next_checkpoint: dict[str, Any] = {
                    "in_progress": True,
                    "status_index": index,
                    "next_page": current_page + 1,
                    "updated_at": utc_iso(),
                }
                if not more:
                    next_checkpoint["status_index"] = index + 1
                    next_checkpoint["next_page"] = 1
                runtime.commit(records, next_checkpoint)
                if not more:
                    break
                current_page += 1

        runtime.commit(
            [],
            {"in_progress": False, "completed_at": utc_iso(), "status_index": 0, "next_page": 1},
        )
