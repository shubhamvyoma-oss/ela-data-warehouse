from __future__ import annotations

from flask import Flask

from app.api.routes import register_routes
from app.config.settings import Settings
from app.database.pool import DatabasePool
from app.logging.setup import configure_logging
from app.monitoring.metrics import MetricsRegistry
from app.queue.file_queue import FileEventQueue
from app.security.rate_limit import InMemoryRateLimiter
from app.services.webhook_service import WebhookService


def create_app(settings: Settings | None = None) -> Flask:
    active_settings = settings or Settings.from_environment()
    configure_logging(active_settings)

    flask_app = Flask(__name__)
    flask_app.config["MAX_CONTENT_LENGTH"] = active_settings.max_payload_bytes

    metrics = MetricsRegistry()
    database = DatabasePool(active_settings)
    queue = FileEventQueue(active_settings)
    rate_limiter = InMemoryRateLimiter(active_settings)
    webhook_service = WebhookService(
        settings=active_settings,
        database=database,
        queue=queue,
        metrics=metrics,
    )

    flask_app.extensions["settings"] = active_settings
    flask_app.extensions["database"] = database
    flask_app.extensions["queue"] = queue
    flask_app.extensions["metrics"] = metrics
    flask_app.extensions["rate_limiter"] = rate_limiter
    flask_app.extensions["webhook_service"] = webhook_service

    register_routes(flask_app)
    return flask_app
