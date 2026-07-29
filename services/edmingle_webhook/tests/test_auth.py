from __future__ import annotations

import hashlib
import hmac
import time

from app.security.auth import WebhookAuthenticator


def test_shared_secret_auth(settings):
    result = WebhookAuthenticator(settings).authenticate({"X-Webhook-Secret": "secret"}, b"{}")

    assert result.allowed is True


def test_invalid_shared_secret_rejected(settings):
    result = WebhookAuthenticator(settings).authenticate({"X-Webhook-Secret": "bad"}, b"{}")

    assert result.allowed is False


def test_authentication_disabled_allows_unsigned_requests(settings):
    disabled_settings = settings.__class__(**{**settings.__dict__, "auth_mode": "disabled"})

    result = WebhookAuthenticator(disabled_settings).authenticate({}, b"{}")

    assert result.allowed is True


def test_hmac_auth(settings):
    hmac_settings = settings.__class__(
        **{**settings.__dict__, "auth_mode": "hmac", "shared_secret": "", "hmac_secret": "hmac-secret"}
    )
    timestamp = str(int(time.time()))
    body = b'{"event_id":"1"}'
    digest = hmac.new(b"hmac-secret", timestamp.encode("utf-8") + b"." + body, hashlib.sha256).hexdigest()

    result = WebhookAuthenticator(hmac_settings).authenticate(
        {"X-Webhook-Timestamp": timestamp, "X-Webhook-Signature": f"sha256={digest}"},
        body,
    )

    assert result.allowed is True
