from __future__ import annotations

import logging
import random
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import urljoin

import requests

from shared.config import EdmingleSettings

LOGGER = logging.getLogger("warehouse.api")


class ApiRequestError(RuntimeError):
    """A safe-to-log API error that excludes response bodies and request URLs."""


class ApiContractError(RuntimeError):
    """The API response did not match the confirmed job contract."""


class EdmingleApiClient:
    def __init__(
        self,
        settings: EdmingleSettings,
        session: requests.Session | None = None,
        *,
        sleep=time.sleep,
        monotonic=time.monotonic,
    ) -> None:
        self.settings = settings
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "apikey": settings.api_key,
                "ORGID": settings.organization_id,
                "Accept": "application/json",
                "User-Agent": "ela-data-warehouse/0.1",
            }
        )
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request_at: float | None = None
        self.request_count = 0

    def get_json(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        context: str,
    ) -> dict[str, Any]:
        url = (
            path
            if path.startswith(("http://", "https://"))
            else urljoin(f"{self.settings.base_url}/", path.lstrip("/"))
        )
        delay = self.settings.initial_retry_delay_seconds
        for attempt in range(1, self.settings.max_retries + 1):
            self._rate_limit()
            self.request_count += 1
            try:
                response = self.session.get(
                    url,
                    params=dict(params or {}),
                    timeout=self.settings.request_timeout_seconds,
                )
            except (requests.Timeout, requests.ConnectionError):
                if attempt == self.settings.max_retries:
                    raise ApiRequestError(f"{context} failed after transient network errors") from None
                self._backoff(delay)
                delay = min(delay * 2, self.settings.maximum_retry_delay_seconds)
                continue
            except requests.RequestException:
                raise ApiRequestError(f"{context} failed with a non-retriable client error") from None

            if response.status_code == 200:
                try:
                    payload = response.json()
                except ValueError:
                    if attempt == self.settings.max_retries:
                        raise ApiContractError(f"{context} returned invalid JSON") from None
                    self._backoff(delay)
                    delay = min(delay * 2, self.settings.maximum_retry_delay_seconds)
                    continue
                if not isinstance(payload, dict):
                    raise ApiContractError(f"{context} returned a non-object JSON response")
                _raise_for_application_error(payload, context)
                return payload

            if response.status_code in {400, 401, 403, 404}:
                raise ApiRequestError(f"{context} returned HTTP {response.status_code}")

            if response.status_code == 429 or response.status_code >= 500:
                if attempt == self.settings.max_retries:
                    raise ApiRequestError(
                        f"{context} exhausted retries after HTTP {response.status_code}"
                    )
                retry_after = _retry_after_seconds(response.headers.get("Retry-After"))
                self._backoff(max(delay, retry_after))
                delay = min(delay * 2, self.settings.maximum_retry_delay_seconds)
                continue

            raise ApiRequestError(f"{context} returned unexpected HTTP {response.status_code}")

        raise ApiRequestError(f"{context} exhausted retries")

    def _rate_limit(self) -> None:
        if self._last_request_at is not None:
            elapsed = self._monotonic() - self._last_request_at
            remaining = self.settings.minimum_request_interval_seconds - elapsed
            if remaining > 0:
                self._sleep(remaining)
        self._last_request_at = self._monotonic()

    def _backoff(self, seconds: float) -> None:
        jitter = random.uniform(0, min(1.0, seconds / 4))
        LOGGER.warning("API request will retry", extra={"backoff_seconds": round(seconds + jitter, 2)})
        self._sleep(seconds + jitter)


def _retry_after_seconds(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return max(0.0, min(float(value), 300.0))
    except ValueError:
        return 0.0


def _raise_for_application_error(payload: dict[str, Any], context: str) -> None:
    """Reject Edmingle errors returned inside an HTTP 200 response without exposing its body."""
    error_code = str(payload.get("error_code") or payload.get("code") or "").strip()
    if error_code == "6001":
        raise ApiRequestError(f"{context} returned Edmingle error 6001 (invalid parameters)")
    if error_code == "6002":
        raise ApiRequestError(f"{context} returned Edmingle error 6002 (authentication failure)")
