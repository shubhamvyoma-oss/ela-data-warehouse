from __future__ import annotations

from datetime import UTC, datetime

import pytest

from api_scripts.api_key_manager.lifecycle import ApiKeyLifecycle, ApiKeyLifecycleError


def test_active_key_allows_production_collection() -> None:
    lifecycle = ApiKeyLifecycle(
        expires_at=datetime(2026, 9, 30, tzinfo=UTC),
        stop_days_before_expiry=3,
    )

    lifecycle.assert_collection_allowed(
        environment="production", now=datetime(2026, 9, 1, tzinfo=UTC)
    )


def test_stop_window_blocks_collection() -> None:
    lifecycle = ApiKeyLifecycle(
        expires_at=datetime(2026, 9, 30, tzinfo=UTC),
        stop_days_before_expiry=3,
    )

    with pytest.raises(ApiKeyLifecycleError, match="renewal window"):
        lifecycle.assert_collection_allowed(
            environment="production", now=datetime(2026, 9, 28, tzinfo=UTC)
        )


def test_unknown_expiry_only_blocks_production() -> None:
    lifecycle = ApiKeyLifecycle(expires_at=None, stop_days_before_expiry=3)

    lifecycle.assert_collection_allowed(environment="development")
    with pytest.raises(ApiKeyLifecycleError, match="required in production"):
        lifecycle.assert_collection_allowed(environment="production")
