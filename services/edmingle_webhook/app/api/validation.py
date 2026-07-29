from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from app.config.settings import Settings
from app.models.event import WebhookEvent


@dataclass(frozen=True)
class ParsedRequest:
    accepted: bool
    status_code: int
    reason: str
    event: WebhookEvent | None


def parse_webhook_request(
    headers: Mapping[str, str],
    raw_body: bytes,
    settings: Settings,
    remote_addr: str,
) -> ParsedRequest:
    content_type = headers.get("Content-Type", "")
    if "application/json" not in content_type.lower():
        return ParsedRequest(False, 415, "content_type_must_be_application_json", None)
    if not raw_body:
        return ParsedRequest(False, 400, "missing_body", None)
    if len(raw_body) > settings.max_payload_bytes:
        return ParsedRequest(False, 413, "payload_too_large", None)

    try:
        decoded_body = raw_body.decode("utf-8")
    except UnicodeDecodeError:
        return ParsedRequest(False, 400, "invalid_utf8", None)

    try:
        payload = json.loads(decoded_body)
    except json.JSONDecodeError:
        return ParsedRequest(False, 400, "malformed_json", None)
    if not isinstance(payload, dict):
        return ParsedRequest(False, 400, "json_body_must_be_object", None)

    event_name = _extract_event_name(payload, settings.event_name_fields)
    event_id = _extract_event_id(payload, settings.event_id_fields, event_name)
    dedup_key = event_id or _fallback_dedup_key(payload, event_name)
    event = WebhookEvent.received_now(
        request_id=str(uuid.uuid4()),
        raw_body=raw_body,
        raw_payload=decoded_body,
        payload_json=_canonical_json(payload),
        event_id=event_id,
        event_name=event_name,
        dedup_key=dedup_key,
        content_type=content_type,
        remote_addr=remote_addr,
        payload_valid=True,
        validation_error="",
    )
    return ParsedRequest(True, 200, "", event)


def _canonical_json(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _find_first_string(payload: dict[str, object], fields: tuple[str, ...]) -> str | None:
    for field in fields:
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, int):
            return str(value)
    return None


def _extract_event_name(payload: dict[str, object], fields: tuple[str, ...]) -> str | None:
    nested = payload.get("event")
    if isinstance(nested, dict):
        nested_name = _find_first_string(nested, fields)
        if nested_name:
            return nested_name
    return _find_first_string(payload, fields)


def _extract_event_id(payload: dict[str, object], fields: tuple[str, ...], event_name: str | None) -> str | None:
    direct = _find_first_string(payload, fields)
    if direct:
        return direct
    nested = payload.get("event")
    if isinstance(nested, dict):
        nested_id = _find_first_string(nested, fields)
        if nested_id:
            return nested_id
        event_ts = nested.get("event_ts")
        if event_name and isinstance(event_ts, str) and event_ts.strip():
            return f"{event_name}:{event_ts.strip()}"
    return None


def _fallback_dedup_key(payload: dict[str, object], event_name: str | None) -> str:
    nested = payload.get("event") if isinstance(payload.get("event"), dict) else {}
    canonical = {
        "event_name": event_name,
        "event_ts": nested.get("event_ts") if isinstance(nested, dict) else payload.get("event_timestamp"),
        "livemode": nested.get("livemode") if isinstance(nested, dict) else payload.get("is_live_mode"),
        "payload": payload.get("payload") if "payload" in payload else payload.get("data", payload),
    }
    return hashlib.sha256(_canonical_json(canonical).encode("utf-8")).hexdigest()
