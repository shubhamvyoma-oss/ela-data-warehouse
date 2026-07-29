from __future__ import annotations

import json
import logging
import urllib.request
from dataclasses import dataclass

from app.config.settings import Settings

logger = logging.getLogger("webhook.security")


@dataclass(frozen=True)
class Alert:
    severity: str
    title: str
    message: str


class AlertManager:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def send(self, alert: Alert) -> None:
        if self._settings.alert_console_enabled:
            logger.warning("alert: %s - %s", alert.title, alert.message, extra={"severity": alert.severity})
        for url in (
            self._settings.slack_webhook_url,
            self._settings.discord_webhook_url,
            self._settings.teams_webhook_url,
        ):
            if url:
                self._post_json(url, {"text": f"[{alert.severity}] {alert.title}: {alert.message}"})

    @staticmethod
    def _post_json(url: str, payload: dict[str, str]) -> None:
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=5).close()
        except Exception:
            logger.exception("alert delivery failed")
