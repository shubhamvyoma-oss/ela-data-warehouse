from __future__ import annotations

from app.config.settings import Settings
from app.database.pool import DatabasePool
from app.logging.setup import configure_logging
from app.monitoring.metrics import MetricsRegistry
from app.queue.file_queue import FileEventQueue
from app.replay.engine import ReplayEngine


def main() -> None:
    settings = Settings.from_environment()
    configure_logging(settings)
    database = DatabasePool(settings)
    queue = FileEventQueue(settings)
    summary = ReplayEngine(settings, database, queue, MetricsRegistry()).run_once()
    print(summary.to_dict())
    database.close()


if __name__ == "__main__":
    main()
