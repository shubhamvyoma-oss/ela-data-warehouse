from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

from collectors.common.edmingle import require_record_list
from collectors.common.models import RawRecord, first_value, stable_record_key
from collectors.common.repositories import utc_iso
from collectors.common.runtime import CollectorRuntime

IST = timezone(timedelta(hours=5, minutes=30), name="IST")


class AttendanceCollector:
    name = "attendance"
    checkpoint_partition_key = "daily"

    def run(self, runtime: CollectorRuntime, checkpoint: dict[str, Any]) -> None:
        start_date, end_date = _collection_window(checkpoint)
        if start_date > end_date:
            runtime.last_checkpoint = checkpoint
            return

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
            records = [_attendance_record(row, current) for row in rows]
            next_checkpoint = {
                "last_completed_date": current.isoformat(),
                "updated_at": utc_iso(),
            }
            runtime.commit(records, next_checkpoint, partition_key="daily")
            current += timedelta(days=1)


def _collection_window(checkpoint: dict[str, Any]) -> tuple[date, date]:
    yesterday = datetime.now(IST).date() - timedelta(days=1)
    end = _optional_date("ATTENDANCE_END_DATE") or yesterday
    explicit_start = _optional_date("ATTENDANCE_START_DATE")
    if explicit_start:
        start = explicit_start
    elif checkpoint.get("last_completed_date"):
        start = date.fromisoformat(str(checkpoint["last_completed_date"])) + timedelta(days=1)
    else:
        lookback = int(os.getenv("ATTENDANCE_LOOKBACK_DAYS", "1"))
        if lookback < 1 or lookback > 3650:
            raise ValueError("ATTENDANCE_LOOKBACK_DAYS must be between 1 and 3650")
        start = end - timedelta(days=lookback - 1)
    return start, end


def _optional_date(name: str) -> date | None:
    raw = os.getenv(name, "").strip()
    return date.fromisoformat(raw) if raw else None


def _attendance_record(row: dict[str, Any], business_date: date) -> RawRecord:
    return RawRecord(
        resource="attendance_records",
        record_key=stable_record_key(
            first_value(row, "student_Id", "student_id"),
            first_value(row, "attendance_id", "attendance_Id"),
            first_value(row, "batch_Id", "batch_id"),
            first_value(row, "class_Id", "class_id"),
            payload=row,
        ),
        payload=row,
        request_context={"business_date": business_date.isoformat(), "report_type": 55},
    )
