from __future__ import annotations

import logging

from flask import Flask, Response, current_app, jsonify, request

from app.api.validation import parse_webhook_request
from app.config.settings import Settings
from app.database.pool import DatabasePool
from app.monitoring.health import HealthChecker
from app.monitoring.metrics import MetricsRegistry
from app.queue.file_queue import FileEventQueue
from app.replay.engine import ReplayEngine
from app.security.auth import WebhookAuthenticator
from app.security.rate_limit import InMemoryRateLimiter

logger = logging.getLogger("webhook.webhook")


def register_routes(app: Flask) -> None:
    @app.after_request
    def add_security_headers(response: Response) -> Response:
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/edmingle/webhook")
    def verify_webhook() -> tuple[Response, int]:
        return jsonify({"status": "ok"}), 200

    @app.post("/edmingle/webhook")
    @app.post("/webhook")
    def receive_webhook() -> tuple[Response, int]:
        settings: Settings = current_app.extensions["settings"]
        metrics: MetricsRegistry = current_app.extensions["metrics"]
        rate_limiter: InMemoryRateLimiter = current_app.extensions["rate_limiter"]
        webhook_service = current_app.extensions["webhook_service"]

        remote_addr = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
        if not rate_limiter.allow(remote_addr):
            metrics.increment("rate_limited_requests")
            return jsonify({"status": "rate_limited"}), 429

        raw_body = request.get_data(cache=False)
        auth_result = WebhookAuthenticator(settings).authenticate(request.headers, raw_body)
        if not auth_result.allowed:
            metrics.increment("authentication_failures")
            return jsonify({"status": "unauthorized"}), 401

        parsed = parse_webhook_request(request.headers, raw_body, settings, remote_addr)
        if not parsed.accepted:
            metrics.increment("invalid_requests")
            logger.warning(
                "webhook request ignored for compatibility",
                extra={"reason": parsed.reason, "remote_addr": remote_addr},
            )
            return jsonify({"status": "ok"}), 200

        result = webhook_service.store_event(parsed.event)
        status_code = (
            200 if result.stored_in_database or result.queued or result.duplicate else settings.total_failure_status
        )
        return (
            jsonify(
                {
                    "status": result.status,
                    "stored_in_database": result.stored_in_database,
                    "queued": result.queued,
                    "duplicate": result.duplicate,
                }
            ),
            status_code,
        )

    @app.get("/live")
    def live() -> tuple[Response, int]:
        return jsonify({"status": "live"}), 200

    @app.get("/health")
    def health() -> tuple[Response, int]:
        return jsonify({"status": "running"}), 200

    @app.get("/ready")
    def ready() -> tuple[Response, int]:
        checker = _health_checker()
        report = checker.check(include_database=True)
        return jsonify(report), 200 if report["status"] == "healthy" else 503

    @app.get("/metrics")
    def metrics() -> tuple[Response, int]:
        registry: MetricsRegistry = current_app.extensions["metrics"]
        queue: FileEventQueue = current_app.extensions["queue"]
        registry.set_gauge("queue_depth", queue.stats().pending_files)
        return Response(registry.prometheus(), mimetype="text/plain; version=0.0.4"), 200

    @app.post("/admin/replay")
    def manual_replay() -> tuple[Response, int]:
        settings: Settings = current_app.extensions["settings"]
        if not settings.admin_token:
            return jsonify({"status": "disabled"}), 403
        supplied = request.headers.get(settings.admin_token_header, "")
        if supplied != settings.admin_token:
            return jsonify({"status": "unauthorized"}), 401
        database: DatabasePool = current_app.extensions["database"]
        queue: FileEventQueue = current_app.extensions["queue"]
        metrics: MetricsRegistry = current_app.extensions["metrics"]
        summary = ReplayEngine(settings, database, queue, metrics).run_once()
        return jsonify(summary.to_dict()), 200


def _health_checker() -> HealthChecker:
    return HealthChecker(
        current_app.extensions["settings"],
        current_app.extensions["database"],
        current_app.extensions["queue"],
    )
