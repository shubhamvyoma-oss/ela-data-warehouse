from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class WebhookEvent:
    request_id: str
    source: str
    received_at: datetime
    raw_body: bytes
    raw_payload: str
    payload_json: str | None
    event_id: str | None
    event_name: str | None
    dedup_key: str
    content_type: str
    remote_addr: str
    payload_valid: bool
    validation_error: str

    @classmethod
    def received_now(
        cls,
        request_id: str,
        raw_body: bytes,
        raw_payload: str,
        payload_json: str | None,
        event_id: str | None,
        event_name: str | None,
        dedup_key: str,
        content_type: str,
        remote_addr: str,
        payload_valid: bool,
        validation_error: str,
    ) -> WebhookEvent:
        return cls(
            request_id=request_id,
            source="edmingle",
            received_at=datetime.now(UTC),
            raw_body=raw_body,
            raw_payload=raw_payload,
            payload_json=payload_json,
            event_id=event_id,
            event_name=event_name,
            dedup_key=dedup_key,
            content_type=content_type,
            remote_addr=remote_addr,
            payload_valid=payload_valid,
            validation_error=validation_error,
        )

    def payload_dict(self) -> dict[str, object]:
        if self.payload_json is None:
            return {}
        payload = json.loads(self.payload_json)
        return payload if isinstance(payload, dict) else {}

    def to_record(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "source": self.source,
            "received_at": self.received_at.isoformat(),
            "raw_payload": self.raw_payload,
            "payload_json": self.payload_json,
            "event_id": self.event_id,
            "event_name": self.event_name,
            "dedup_key": self.dedup_key,
            "content_type": self.content_type,
            "remote_addr": self.remote_addr,
            "payload_valid": self.payload_valid,
            "validation_error": self.validation_error,
        }

    @classmethod
    def from_record(cls, record: dict[str, object]) -> WebhookEvent:
        return cls(
            request_id=str(record["request_id"]),
            source=str(record["source"]),
            received_at=datetime.fromisoformat(str(record["received_at"])),
            raw_body=str(record["raw_payload"]).encode("utf-8"),
            raw_payload=str(record["raw_payload"]),
            payload_json=str(record["payload_json"]) if record.get("payload_json") is not None else None,
            event_id=str(record["event_id"]) if record.get("event_id") is not None else None,
            event_name=str(record["event_name"]) if record.get("event_name") is not None else None,
            dedup_key=str(record["dedup_key"]),
            content_type=str(record["content_type"]),
            remote_addr=str(record["remote_addr"]),
            payload_valid=bool(record["payload_valid"]),
            validation_error=str(record["validation_error"]),
        )
