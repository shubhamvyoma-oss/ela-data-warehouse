from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.config.settings import Settings
from app.models.event import WebhookEvent

logger = logging.getLogger("webhook.queue")


class QueueRecordError(Exception):
    """Raised when a queue file cannot be parsed safely."""


@dataclass(frozen=True)
class QueueStats:
    pending_files: int
    processing_files: int
    failed_files: int
    archive_files: int
    buffer_bytes: int
    status: str = "ok"

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "pending_files": self.pending_files,
            "processing_files": self.processing_files,
            "failed_files": self.failed_files,
            "archive_files": self.archive_files,
            "buffer_bytes": self.buffer_bytes,
        }


class FileEventQueue:
    _claim_lock = threading.Lock()

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        for directory in (
            settings.buffer_directory,
            settings.processing_directory,
            settings.failed_directory,
            settings.archive_directory,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def enqueue(self, event: WebhookEvent, reason: str) -> Path:
        record = event.to_record()
        record["queue_reason"] = reason
        record["attempts"] = 0
        file_name = f"{event.received_at.strftime('%Y%m%d%H%M%S%f')}-{event.request_id}-{uuid.uuid4().hex}.jsonl"
        final_path = self._settings.buffer_directory / file_name
        temp_path = final_path.with_suffix(".tmp")
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        with temp_path.open("xb") as handle:
            handle.write(line.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, final_path)
        self._fsync_directory(self._settings.buffer_directory)
        return final_path

    def pending_files(self, limit: int | None = None) -> list[Path]:
        self.recover_stale_claims()
        files = sorted(self._settings.buffer_directory.glob("*.jsonl"))
        return files if limit is None else files[:limit]

    def claim(self, path: Path) -> Path | None:
        destination = self._settings.processing_directory / f"{uuid.uuid4().hex}.{path.name}"
        with self._claim_lock:
            try:
                os.rename(path, destination)
                return destination
            except (FileNotFoundError, FileExistsError, PermissionError):
                return None

    def read_event(self, path: Path) -> WebhookEvent:
        return WebhookEvent.from_record(self.read_record(path))

    def read_record(self, path: Path) -> dict[str, object]:
        try:
            with path.open("r", encoding="utf-8") as handle:
                line = handle.readline()
            if not line:
                raise QueueRecordError("empty_queue_file")
            return json.loads(line)
        except json.JSONDecodeError as exc:
            raise QueueRecordError("invalid_queue_json") from exc
        except UnicodeDecodeError as exc:
            raise QueueRecordError("invalid_queue_encoding") from exc

    def return_for_retry(self, path: Path, reason: str) -> tuple[int, Path]:
        record = self.read_record(path)
        attempts = int(record.get("attempts", 0)) + 1
        record["attempts"] = attempts
        record["last_error"] = reason
        retry_path = self._settings.buffer_directory / self._original_queue_name(path)
        temp_path = retry_path.with_suffix(".retry")
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        with temp_path.open("xb") as handle:
            handle.write(line.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, retry_path)
        path.unlink(missing_ok=True)
        self._fsync_directory(self._settings.buffer_directory)
        return attempts, retry_path

    def archive(self, path: Path) -> Path:
        destination = self._unique_destination(self._settings.archive_directory / path.name)
        shutil.move(str(path), destination)
        return destination

    def fail(self, path: Path) -> Path:
        destination = self._unique_destination(self._settings.failed_directory / path.name)
        shutil.move(str(path), destination)
        return destination

    def fail_corrupt(self, path: Path, reason: str) -> Path:
        size = path.stat().st_size if path.exists() else 0
        failed_path = self.fail(path)
        metadata = {
            "original_filename": self._original_queue_name(path),
            "failed_filename": failed_path.name,
            "failure_reason": reason,
            "detected_at": datetime.now(UTC).isoformat(),
            "file_size": size,
        }
        sidecar = self._unique_destination(failed_path.with_suffix(failed_path.suffix + ".failure.json"))
        sidecar.write_text(json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        logger.warning("corrupt queue file dead-lettered", extra={"queue_file": path.name, "reason": reason})
        return failed_path

    def recover_stale_claims(self) -> int:
        recovered = 0
        cutoff = time.time() - self._settings.queue_claim_timeout_seconds
        for path in sorted(self._settings.processing_directory.glob("*.jsonl")):
            if path.stat().st_mtime >= cutoff:
                continue
            destination = self._unique_destination(self._settings.buffer_directory / self._original_queue_name(path))
            shutil.move(str(path), destination)
            logger.warning("stale queue claim recovered", extra={"queue_file": path.name})
            recovered += 1
        return recovered

    def stats(self) -> QueueStats:
        pending = list(self._settings.buffer_directory.glob("*.jsonl"))
        processing = list(self._settings.processing_directory.glob("*.jsonl"))
        failed = list(self._settings.failed_directory.glob("*.jsonl"))
        archive = list(self._settings.archive_directory.glob("*.jsonl"))
        return QueueStats(
            pending_files=len(pending),
            processing_files=len(processing),
            failed_files=len(failed),
            archive_files=len(archive),
            buffer_bytes=sum(path.stat().st_size for path in pending),
        )

    @staticmethod
    def _unique_destination(path: Path) -> Path:
        if not path.exists():
            return path
        return path.with_name(f"{path.stem}-{uuid.uuid4().hex}{path.suffix}")

    @staticmethod
    def _original_queue_name(path: Path) -> str:
        prefix, separator, original = path.name.partition(".")
        if separator and len(prefix) == 32:
            return original
        return path.name

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        if os.name == "nt":
            return
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
