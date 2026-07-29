from __future__ import annotations

import threading

from app.api.validation import parse_webhook_request
from app.database.pool import InsertResult
from app.monitoring.metrics import MetricsRegistry
from app.services.webhook_service import WebhookService


class FakeDatabase:
    def __init__(self, result: InsertResult | None = None, error: Exception | None = None) -> None:
        self.result = result or InsertResult(inserted=True, duplicate=False, webhook_event_id=1)
        self.error = error

    def insert_event(self, event):
        if self.error:
            raise self.error
        return self.result


class FakeQueue:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.enqueued = 0

    def enqueue(self, event, reason: str):
        if self.error:
            raise self.error
        self.enqueued += 1
        return "queued.jsonl"


class ConcurrentDedupDatabase:
    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._lock = threading.Lock()

    def insert_event(self, event):
        with self._lock:
            if event.dedup_key in self._seen:
                return InsertResult(inserted=False, duplicate=True, webhook_event_id=None)
            self._seen.add(event.dedup_key)
            return InsertResult(inserted=True, duplicate=False, webhook_event_id=1)


def _event(settings):
    parsed = parse_webhook_request(
        {"Content-Type": "application/json"},
        b'{"event_id":"evt-service","event":"user.user_created"}',
        settings,
        "127.0.0.1",
    )
    assert parsed.event is not None
    return parsed.event


def test_db_insert_success(settings):
    result = WebhookService(settings, FakeDatabase(), FakeQueue(), MetricsRegistry()).store_event(_event(settings))

    assert result.status == "stored"
    assert result.stored_in_database is True
    assert result.queued is False


def test_db_insert_failure_with_queue_success(settings):
    queue = FakeQueue()
    result = WebhookService(
        settings,
        FakeDatabase(error=RuntimeError("db down")),
        queue,
        MetricsRegistry(),
    ).store_event(_event(settings))

    assert result.status == "queued"
    assert result.stored_in_database is False
    assert result.queued is True
    assert queue.enqueued == 1


def test_db_insert_failure_with_queue_failure(settings):
    result = WebhookService(
        settings,
        FakeDatabase(error=RuntimeError("db down")),
        FakeQueue(error=RuntimeError("disk full")),
        MetricsRegistry(),
    ).store_event(_event(settings))

    assert result.status == "failed"
    assert result.stored_in_database is False
    assert result.queued is False


def test_duplicate_delivery(settings):
    result = WebhookService(
        settings,
        FakeDatabase(InsertResult(inserted=False, duplicate=True, webhook_event_id=None)),
        FakeQueue(),
        MetricsRegistry(),
    ).store_event(_event(settings))

    assert result.status == "duplicate"
    assert result.duplicate is True


def test_concurrent_duplicate_delivery(settings):
    database = ConcurrentDedupDatabase()
    service = WebhookService(settings, database, FakeQueue(), MetricsRegistry())
    event = _event(settings)
    results = []

    threads = [threading.Thread(target=lambda: results.append(service.store_event(event))) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(result.status for result in results) == ["duplicate", "stored"]
