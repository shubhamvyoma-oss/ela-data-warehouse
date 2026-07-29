from __future__ import annotations

import signal
import time

from app.config.settings import Settings
from app.database.pool import DatabasePool
from app.logging.setup import configure_logging
from app.monitoring.metrics import MetricsRegistry
from app.queue.file_queue import FileEventQueue
from app.replay.engine import ReplayEngine

running = True


def stop_worker(signum: int, frame: object) -> None:
    global running
    running = False


def main() -> None:
    signal.signal(signal.SIGTERM, stop_worker)
    signal.signal(signal.SIGINT, stop_worker)
    settings = Settings.from_environment()
    configure_logging(settings)
    database = DatabasePool(settings)
    queue = FileEventQueue(settings)
    engine = ReplayEngine(settings, database, queue, MetricsRegistry())
    while running:
        engine.run_once()
        time.sleep(settings.replay_backoff_seconds)
    database.close()


if __name__ == "__main__":
    main()
