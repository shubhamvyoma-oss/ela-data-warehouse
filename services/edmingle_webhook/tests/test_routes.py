from __future__ import annotations

from dataclasses import dataclass

from app.main import create_app
from app.models.result import StoreResult


@dataclass
class FakeWebhookService:
    result: StoreResult | None = None
    raised: Exception | None = None
    calls: int = 0

    def store_event(self, event):
        self.calls += 1
        if self.raised:
            raise self.raised
        return self.result or StoreResult("stored", stored_in_database=True, queued=False, duplicate=False)


def _client(settings, service: FakeWebhookService | None = None):
    disabled_settings = settings.__class__(**{**settings.__dict__, "auth_mode": "disabled"})
    app = create_app(disabled_settings)
    app.extensions["webhook_service"] = service or FakeWebhookService()
    return app.test_client()


def test_get_edmingle_webhook_validation(settings):
    response = _client(settings).get("/edmingle/webhook")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_health_preserves_live_contract(settings):
    response = _client(settings).get("/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "running"}


def test_post_edmingle_webhook_success(settings):
    service = FakeWebhookService()
    response = _client(settings, service).post(
        "/edmingle/webhook", json={"event_id": "evt-1", "event": "user.user_created"}
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "stored"
    assert service.calls == 1


def test_post_webhook_alias_uses_same_handler(settings):
    service = FakeWebhookService()
    response = _client(settings, service).post("/webhook", json={"event_id": "evt-2", "event": "user.user_created"})

    assert response.status_code == 200
    assert response.get_json()["status"] == "stored"
    assert service.calls == 1


def test_invalid_json_returns_compatibility_ok_without_insert(settings):
    service = FakeWebhookService()
    response = _client(settings, service).post("/edmingle/webhook", data="{", content_type="application/json")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}
    assert service.calls == 0


def test_empty_body_returns_compatibility_ok_without_insert(settings):
    service = FakeWebhookService()
    response = _client(settings, service).post("/edmingle/webhook", data=b"", content_type="application/json")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}
    assert service.calls == 0


def test_json_null_returns_compatibility_ok_without_insert(settings):
    service = FakeWebhookService()
    response = _client(settings, service).post("/edmingle/webhook", data="null", content_type="application/json")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}
    assert service.calls == 0


def test_json_array_returns_compatibility_ok_without_insert(settings):
    service = FakeWebhookService()
    response = _client(settings, service).post("/webhook", data="[]", content_type="application/json")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}
    assert service.calls == 0


def test_duplicate_delivery_returns_200(settings):
    service = FakeWebhookService(StoreResult("duplicate", stored_in_database=False, queued=False, duplicate=True))
    response = _client(settings, service).post(
        "/edmingle/webhook", json={"event_id": "evt-dup", "event": "user.user_created"}
    )

    assert response.status_code == 200
    assert response.get_json()["duplicate"] is True


def test_queued_delivery_returns_200_without_claiming_stored(settings):
    service = FakeWebhookService(StoreResult("queued", stored_in_database=False, queued=True, duplicate=False))
    response = _client(settings, service).post(
        "/edmingle/webhook", json={"event_id": "evt-queued", "event": "user.user_created"}
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["queued"] is True
    assert body["stored_in_database"] is False


def test_database_and_queue_failure_returns_503(settings):
    service = FakeWebhookService(StoreResult("failed", stored_in_database=False, queued=False, duplicate=False))
    response = _client(settings, service).post(
        "/edmingle/webhook", json={"event_id": "evt-failed", "event": "user.user_created"}
    )

    assert response.status_code == 503


def test_total_failure_status_can_be_500(settings):
    status_settings = settings.__class__(**{**settings.__dict__, "total_failure_status": 500})
    service = FakeWebhookService(StoreResult("failed", stored_in_database=False, queued=False, duplicate=False))
    response = _client(status_settings, service).post(
        "/edmingle/webhook",
        json={"event_id": "evt-failed", "event": "user.user_created"},
    )

    assert response.status_code == 500
