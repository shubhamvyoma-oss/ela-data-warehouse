from __future__ import annotations

import logging
from dataclasses import dataclass

from app.config.settings import Settings
from app.database.pool import DatabasePool
from app.monitoring.metrics import MetricsRegistry
from app.queue.file_queue import FileEventQueue, QueueRecordError

logger = logging.getLogger("webhook.replay")


@dataclass(frozen=True)
class ReplaySummary:
    scanned: int
    stored: int
    duplicates: int
    failed: int
    archived: int
    dead_lettered: int

    def to_dict(self) -> dict[str, int]:
        return self.__dict__.copy()


class ReplayEngine:
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

    def run_once(self) -> ReplaySummary:
        scanned = stored = duplicates = failed = archived = dead_lettered = 0
        for path in self._queue.pending_files(self._settings.replay_batch_size):
            claimed_path = self._queue.claim(path)
            if claimed_path is None:
                continue
            scanned += 1
            try:
                event = self._queue.read_event(claimed_path)
                result = self._database.insert_event(event)
                if result.inserted:
                    stored += 1
                    self._metrics.increment("replayed_events")
                if result.duplicate:
                    duplicates += 1
                    self._metrics.increment("duplicates")
                self._queue.archive(claimed_path)
                archived += 1
            except QueueRecordError as exc:
                failed += 1
                dead_lettered += 1
                logger.warning(
                    "queue record is unreadable; moving to failed",
                    extra={"queue_file": claimed_path.name, "reason": str(exc)},
                )
                self._queue.fail_corrupt(claimed_path, str(exc))
                self._metrics.increment("replay_failures")
            except Exception:
                failed += 1
                logger.exception("replay failed", extra={"queue_file": claimed_path.name})
                attempts, retry_path = self._queue.return_for_retry(claimed_path, "database_insert_failed")
                if attempts >= self._settings.replay_max_attempts:
                    self._queue.fail(retry_path)
                    dead_lettered += 1
                self._metrics.increment("replay_failures")
        return ReplaySummary(scanned, stored, duplicates, failed, archived, dead_lettered)
