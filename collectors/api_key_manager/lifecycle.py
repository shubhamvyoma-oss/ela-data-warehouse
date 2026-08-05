from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from shared.config import EdmingleSettings


class ApiKeyLifecycleError(RuntimeError):
    pass


@dataclass(frozen=True)
class ApiKeyLifecycle:
    expires_at: datetime | None
    stop_days_before_expiry: int

    @classmethod
    def from_settings(cls, settings: EdmingleSettings) -> ApiKeyLifecycle:
        return cls(
            expires_at=_parse_expiry(settings.api_key_expires_at),
            stop_days_before_expiry=settings.api_key_stop_days_before_expiry,
        )

    def status(self, now: datetime | None = None) -> str:
        if self.expires_at is None:
            return "unknown"
        current = now or datetime.now(UTC)
        if current >= self.expires_at:
            return "expired"
        stop_at = self.expires_at - timedelta(days=self.stop_days_before_expiry)
        return "stop_window" if current >= stop_at else "active"

    def assert_collection_allowed(
        self,
        *,
        environment: str,
        now: datetime | None = None,
    ) -> None:
        status = self.status(now)
        if status == "unknown" and environment == "production":
            raise ApiKeyLifecycleError(
                "EDMINGLE_API_KEY_EXPIRES_AT is required in production"
            )
        if status == "expired":
            raise ApiKeyLifecycleError("Edmingle API key is expired")
        if status == "stop_window":
            raise ApiKeyLifecycleError(
                "collection is paused inside the configured API-key renewal window"
            )


def _parse_expiry(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed_date = date.fromisoformat(value)
        except ValueError as exc:
            raise ApiKeyLifecycleError(
                "EDMINGLE_API_KEY_EXPIRES_AT must be an ISO date or timestamp"
            ) from exc
        parsed = datetime.combine(parsed_date, time.max, tzinfo=UTC)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
