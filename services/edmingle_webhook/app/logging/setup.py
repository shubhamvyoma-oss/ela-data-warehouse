from __future__ import annotations

import gzip
import json
import logging
import logging.handlers
import shutil
from datetime import UTC, datetime
from pathlib import Path

from app.config.settings import Settings


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key not in _RESERVED_RECORD_FIELDS and isinstance(value, str | int | float | bool | None):
                payload[key] = value
        return json.dumps(payload, ensure_ascii=False)


class CompressingRotatingFileHandler(logging.handlers.RotatingFileHandler):
    def doRollover(self) -> None:
        super().doRollover()
        rotated = Path(f"{self.baseFilename}.1")
        if rotated.exists():
            compressed = rotated.with_suffix(rotated.suffix + ".gz")
            with rotated.open("rb") as source, gzip.open(compressed, "wb") as target:
                shutil.copyfileobj(source, target)
            rotated.unlink()


def configure_logging(settings: Settings) -> None:
    settings.log_directory.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(settings.log_level)

    formatter: logging.Formatter
    formatter = (
        JsonFormatter() if settings.log_json else logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    for name in ("webhook", "errors", "replay", "database", "queue", "security", "startup", "health", "metrics"):
        logger = logging.getLogger(f"webhook.{name}")
        handler = CompressingRotatingFileHandler(
            settings.log_directory / f"{name}.log",
            maxBytes=settings.log_max_bytes,
            backupCount=settings.log_backup_count,
            encoding="utf-8",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.propagate = True


_RESERVED_RECORD_FIELDS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
}
