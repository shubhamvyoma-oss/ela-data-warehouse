from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def payload_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def stable_record_key(*values: Any, payload: Any) -> str:
    normalized = [str(value).strip() for value in values if value is not None and str(value).strip()]
    if normalized:
        return "|".join(f"{len(value)}:{value}" for value in normalized)
    return f"sha256:{payload_sha256(payload)}"


def first_value(item: dict[str, Any], *names: str) -> Any:
    for name in names:
        value = item.get(name)
        if value is not None and value != "":
            return value
    return None


@dataclass(frozen=True)
class RawRecord:
    resource: str
    record_key: str
    payload: dict[str, Any]
    request_context: dict[str, Any] = field(default_factory=dict)
    source_updated_at: datetime | None = None
    received_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def checksum(self) -> str:
        return payload_sha256(self.payload)


@dataclass
class JobStats:
    rows_read: int = 0
    rows_written: int = 0
    rows_rejected: int = 0
    request_count: int = 0
