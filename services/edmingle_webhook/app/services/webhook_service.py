from __future__ import annotations

import logging
import time

from app.config.settings import Settings
from app.database.pool import DatabasePool
from app.models.event import WebhookEvent
from app.models.result import StoreResult
from app.monitoring.metrics import MetricsRegistry
from app.queue.file_queue import FileEventQueue

logger = logging.getLogger("webhook.webhook")
error_logger = logging.getLogger("webhook.errors")


class WebhookService:
    def __init__(
        self,
        settings: Settings,
        database: DatabasePool,
        queue: FileEventQueue,
        metrics: MetricsRegistry,
    ) -> None:
        self._settings = settings
        self._database = database
        self._queue = queue
        self._metrics = metrics

    def store_event(self, event: WebhookEvent) -> StoreResult:
        started_at = time.monotonic()
        self._metrics.increment("received_events")
        try:
            result = self._database.insert_event(event)
            if result.duplicate:
                self._metrics.increment("duplicates")
                return StoreResult("duplicate", stored_in_database=False, queued=False, duplicate=True)
            self._metrics.increment("stored_events")
            logger.info("webhook stored", extra={"request_id": event.request_id, "event_id": event.event_id})
            return StoreResult("stored", stored_in_database=True, queued=False, duplicate=False)
        except Exception as exc:
            self._metrics.increment("database_failures")
            error_logger.exception("database unavailable; queueing webhook", extra={"request_id": event.request_id})
            try:
                self._queue.enqueue(event, reason=str(exc))
                self._metrics.increment("queued_events")
                return StoreResult("queued", stored_in_database=False, queued=True, duplicate=False)
            except Exception:
                self._metrics.increment("queue_failures")
                error_logger.exception("critical queue failure", extra={"request_id": event.request_id})
                return StoreResult("failed", stored_in_database=False, queued=False, duplicate=False)
        finally:
            self._metrics.observe_latency(time.monotonic() - started_at)
