from __future__ import annotations

import os
import threading
import time

from app.api.validation import parse_webhook_request
from app.database.pool import InsertResult
from app.monitoring.metrics import MetricsRegistry
from app.queue.file_queue import FileEventQueue
from app.replay.engine import ReplayEngine


class FakeDatabase:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0
        self._lock = threading.Lock()

    def insert_event(self, event):
        with self._lock:
            self.calls += 1
        if self.error:
            raise self.error
        return InsertResult(inserted=True, duplicate=False, webhook_event_id=1)


def _queued_event(settings):
    parsed = parse_webhook_request(
        {"Content-Type": "application/json"},
        b'{"event_id":"evt-replay","event":"user.user_created"}',
        settings,
        "127.0.0.1",
    )
    assert parsed.event is not None
    queue = FileEventQueue(settings)
    queue.enqueue(parsed.event, "db down")
    return queue


def test_replay_success_archives_file(settings):
    queue = _queued_event(settings)

    summary = ReplayEngine(settings, FakeDatabase(), queue, MetricsRegistry()).run_once()

    assert summary.scanned == 1
    assert summary.stored == 1
    assert summary.archived == 1
    assert queue.stats().pending_files == 0
    assert queue.stats().archive_files == 1


def test_replay_failure_increments_attempts(settings):
    queue = _queued_event(settings)

    summary = ReplayEngine(settings, FakeDatabase(RuntimeError("db down")), queue, MetricsRegistry()).run_once()
    record = queue.read_record(queue.pending_files()[0])

    assert summary.failed == 1
    assert record["attempts"] == 1
    assert queue.stats().failed_files == 0


def test_replay_dead_letters_after_max_attempts(settings):
    queue = _queued_event(settings)

    ReplayEngine(settings, FakeDatabase(RuntimeError("db down")), queue, MetricsRegistry()).run_once()
    summary = ReplayEngine(settings, FakeDatabase(RuntimeError("db down")), queue, MetricsRegistry()).run_once()

    assert summary.dead_lettered == 1
    assert queue.stats().pending_files == 0
    assert queue.stats().failed_files == 1


def test_two_replay_workers_claim_one_item_once(settings):
    queue = _queued_event(settings)
    database = FakeDatabase()
    summaries = []

    def run_worker():
        summaries.append(ReplayEngine(settings, database, queue, MetricsRegistry()).run_once())

    threads = [threading.Thread(target=run_worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert database.calls == 1
    assert sum(summary.scanned for summary in summaries) == 1
    assert queue.stats().archive_files == 1


def test_stale_claim_recovery_returns_file_to_buffer(settings):
    queue = _queued_event(settings)
    pending = queue.pending_files()[0]
    claimed = queue.claim(pending)
    assert claimed is not None
    old_time = time.time() - settings.queue_claim_timeout_seconds - 1
    os.utime(claimed, (old_time, old_time))

    recovered = queue.recover_stale_claims()

    assert recovered == 1
    assert queue.stats().pending_files == 1
    assert queue.stats().processing_files == 0


def test_invalid_json_queue_file_dead_letters(settings):
    queue = FileEventQueue(settings)
    corrupt = settings.buffer_directory / "corrupt.jsonl"
    corrupt.write_text("{", encoding="utf-8")

    summary = ReplayEngine(settings, FakeDatabase(), queue, MetricsRegistry()).run_once()

    assert summary.dead_lettered == 1
    assert queue.stats().failed_files == 1
    assert list(settings.failed_directory.glob("*.failure.json"))


def test_empty_queue_file_dead_letters(settings):
    queue = FileEventQueue(settings)
    empty = settings.buffer_directory / "empty.jsonl"
    empty.write_text("", encoding="utf-8")

    summary = ReplayEngine(settings, FakeDatabase(), queue, MetricsRegistry()).run_once()

    assert summary.dead_lettered == 1
    assert queue.stats().failed_files == 1
    assert list(settings.failed_directory.glob("*.failure.json"))


def test_corrupt_file_does_not_block_valid_file(settings):
    queue = _queued_event(settings)
    corrupt = settings.buffer_directory / "truncated.jsonl"
    corrupt.write_text('{"request_id"', encoding="utf-8")

    summary = ReplayEngine(settings, FakeDatabase(), queue, MetricsRegistry()).run_once()

    assert summary.scanned == 2
    assert summary.stored == 1
    assert summary.dead_lettered == 1
    assert queue.stats().archive_files == 1
    assert queue.stats().failed_files == 1
