from __future__ import annotations

from app.api.validation import parse_webhook_request
from app.queue.file_queue import FileEventQueue


def test_queue_writes_and_reads_jsonl(settings):
    parsed = parse_webhook_request(
        {"Content-Type": "application/json"},
        b'{"event_id":"queued"}',
        settings,
        "127.0.0.1",
    )
    assert parsed.event is not None
    queue = FileEventQueue(settings)

    path = queue.enqueue(parsed.event, "database_down")
    restored = queue.read_event(path)

    assert path.suffix == ".jsonl"
    assert restored.event_id == "queued"
    assert queue.stats().pending_files == 1
    assert settings.buffer_directory.exists()
    assert settings.failed_directory.exists()
    assert settings.archive_directory.exists()
