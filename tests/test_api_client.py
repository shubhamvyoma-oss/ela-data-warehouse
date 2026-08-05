from __future__ import annotations

from dataclasses import replace

import pytest
import requests

from api_scripts.common.api_client import ApiContractError, ApiRequestError, EdmingleApiClient
from shared.config import EdmingleSettings


class FakeResponse:
    def __init__(self, status_code: int, payload=None, headers=None) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.headers: dict[str, str] = {}
        self.calls = 0

    def get(self, *_args, **_kwargs):
        self.calls += 1
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture
def settings() -> EdmingleSettings:
    return EdmingleSettings(
        base_url="https://example.invalid/api",
        api_key="secret",
        api_key_expires_at="",
        api_key_stop_days_before_expiry=3,
        organization_id="483",
        institute_id="483",
        request_timeout_seconds=5,
        max_retries=3,
        minimum_request_interval_seconds=0,
    )


def test_client_retries_rate_limit_without_logging_payload(settings: EdmingleSettings) -> None:
    session = FakeSession(
        [FakeResponse(429, headers={"Retry-After": "0"}), FakeResponse(200, {"data": []})]
    )
    client = EdmingleApiClient(settings, session=session, sleep=lambda _: None)

    assert client.get_json("/records", context="test") == {"data": []}
    assert session.calls == 2


def test_client_rejects_permanent_status(settings: EdmingleSettings) -> None:
    client = EdmingleApiClient(
        settings,
        session=FakeSession([FakeResponse(401, {"private": "body"})]),
        sleep=lambda _: None,
    )

    with pytest.raises(ApiRequestError, match="HTTP 401") as error:
        client.get_json("/records", context="test")
    assert "private" not in str(error.value)
    assert "secret" not in str(error.value)


def test_client_rejects_non_object_json(settings: EdmingleSettings) -> None:
    client = EdmingleApiClient(
        replace(settings, max_retries=1),
        session=FakeSession([FakeResponse(200, [1, 2])]),
        sleep=lambda _: None,
    )

    with pytest.raises(ApiContractError, match="non-object"):
        client.get_json("/records", context="test")


def test_client_converts_timeout_to_safe_error(settings: EdmingleSettings) -> None:
    client = EdmingleApiClient(
        replace(settings, max_retries=1),
        session=FakeSession([requests.Timeout("secret URL")]),
        sleep=lambda _: None,
    )

    with pytest.raises(ApiRequestError) as error:
        client.get_json("/records", context="test")
    assert "secret URL" not in str(error.value)
