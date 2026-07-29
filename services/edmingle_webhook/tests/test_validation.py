from __future__ import annotations

from app.api.validation import parse_webhook_request


def test_valid_json_request_creates_event(settings):
    parsed = parse_webhook_request(
        {"Content-Type": "application/json"},
        b'{"event_id":"abc","event":"created"}',
        settings,
        "127.0.0.1",
    )

    assert parsed.accepted is True
    assert parsed.event is not None
    assert parsed.event.event_id == "abc"
    assert parsed.event.dedup_key == "abc"


def test_nested_edmingle_payload_creates_stable_event_identity(settings):
    parsed = parse_webhook_request(
        {"Content-Type": "application/json"},
        b'{"event":{"event":"user.user_created","event_ts":"2026-07-29T12:00:00+00:00","livemode":true},"payload":{"user_id":123}}',
        settings,
        "127.0.0.1",
    )

    assert parsed.accepted is True
    assert parsed.event is not None
    assert parsed.event.event_name == "user.user_created"
    assert parsed.event.event_id == "user.user_created:2026-07-29T12:00:00+00:00"


def test_malformed_json_is_rejected(settings):
    parsed = parse_webhook_request({"Content-Type": "application/json"}, b"{", settings, "127.0.0.1")

    assert parsed.accepted is False
    assert parsed.status_code == 400
    assert parsed.reason == "malformed_json"


def test_non_json_content_type_is_rejected(settings):
    parsed = parse_webhook_request({"Content-Type": "text/plain"}, b"hello", settings, "127.0.0.1")

    assert parsed.accepted is False
    assert parsed.status_code == 415
