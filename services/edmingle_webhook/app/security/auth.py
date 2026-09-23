from __future__ import annotations

import hashlib
import hmac
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass

from app.config.settings import Settings


@dataclass(frozen=True)
class AuthResult:
    allowed: bool
    reason: str = ""


class WebhookAuthenticator:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def authenticate(self, headers: Mapping[str, str], raw_body: bytes) -> AuthResult:
        if self._settings.auth_mode == "disabled":
            return AuthResult(True)
        if self._settings.auth_mode == "shared_secret" and self._shared_secret_valid(headers):
            return AuthResult(True)
        if self._settings.auth_mode == "hmac" and self._hmac_valid(headers, raw_body):
            return AuthResult(True)
        return AuthResult(False, "invalid_authentication")

    def _shared_secret_valid(self, headers: Mapping[str, str]) -> bool:
        supplied = headers.get(self._settings.shared_secret_header, "")
        return hmac.compare_digest(supplied, self._settings.shared_secret)

    def _hmac_valid(self, headers: Mapping[str, str], raw_body: bytes) -> bool:
        signature = headers.get(self._settings.hmac_signature_header, "")
        timestamp = headers.get(self._settings.hmac_timestamp_header, "")
        if not signature or not timestamp:
            return False
        try:
            request_time = int(timestamp)
        except ValueError:
            return False
        if abs(int(time.time()) - request_time) > self._settings.signature_tolerance_seconds:
            return False
        nonce = headers.get(self._settings.hmac_nonce_header, "")
        if nonce and not _nonce_store.remember(nonce, self._settings.signature_tolerance_seconds):
            return False
        signed_body = timestamp.encode("utf-8") + b"." + raw_body
        digest = hmac.new(self._settings.hmac_secret.encode("utf-8"), signed_body, hashlib.sha256).hexdigest()
        expected = f"sha256={digest}"
        return hmac.compare_digest(signature, expected) or hmac.compare_digest(signature, digest)


class _NonceStore:
    """Per-process, in-memory HMAC-nonce replay guard.

    KNOWN LIMITATION -- same class of gap as InMemoryRateLimiter (see
    app/security/rate_limit.py and docs/architecture.md's Rate Limiting
    section): state lives in plain process memory, not a shared store. The
    Dockerfile runs gunicorn with multiple worker processes (currently 2),
    each holding its own independent nonce set for the same client. A nonce
    already "seen" by one worker is NOT rejected if the replayed request
    happens to land on a different worker -- replay protection is therefore
    weaker than WEBHOOK_AUTH_MODE=hmac alone would suggest. Currently
    low-risk in practice: WEBHOOK_AUTH_MODE is "disabled" in production
    today (see .env), so this path isn't live. Documented here, rather than
    fixed with a new external dependency (e.g. Redis), for the same reason
    the rate limiter accepts its equivalent gap -- flag before enabling
    WEBHOOK_AUTH_MODE=hmac for real.
    """

    def __init__(self) -> None:
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def remember(self, nonce: str, ttl_seconds: int) -> bool:
        now = time.time()
        expires_at = now + ttl_seconds
        with self._lock:
            for key, value in list(self._seen.items()):
                if value < now:
                    self._seen.pop(key, None)
            if nonce in self._seen:
                return False
            self._seen[nonce] = expires_at
            return True


_nonce_store = _NonceStore()
