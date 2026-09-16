"""Generate a new Edmingle tutor API key and deliver it by email.

Ports the standalone legacy scripts (`edmingle_generate_api_key.py`,
`edmingle_api_key_email.py`, `edmingle_api_key_settings.py`) into this
warehouse so key generation can be scripted going forward instead of run by
hand from a laptop. `../api_key_manager/README.md` previously deferred
automated generation "until the key-generation endpoint, authentication
contract, and redacted response sample are supplied"; the legacy script is
that confirmed contract (it has been exercised against the real endpoint),
and this port proceeds per explicit project-owner approval to close that
gap now. Hardcoded credential VALUES from the legacy settings file are
intentionally NOT carried over -- they become environment variables here.

CRITICAL -- the generated API key value must never be logged, printed,
persisted to the database, written to a file, or otherwise retained by this
codebase. It lives only in a local variable for the few lines between the
login call and the email send, and is discarded immediately after.  See
../api_key_manager/README.md: "API key values must never be stored in
PostgreSQL, logs, audit events, YAML, or Git." The database write this
module performs carries only lifecycle metadata (expires_at, status) --
never the key itself.

Unlike the read-only, API-key-authenticated collectors elsewhere in
api_scripts/, this module authenticates with a username and password. It
must never be invoked as part of routine/automatic pipeline runs or tests --
only deliberately, by an operator who intends to rotate the key.
"""

from __future__ import annotations

import json
import logging
import os
import smtplib
import ssl
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Any

import requests

from api_scripts.common.repositories import CredentialMetadataRepository
from shared.config import DatabaseSettings
from shared.database import Database

LOGGER = logging.getLogger("warehouse.edmingle_api_key_generator.generate")

_USER_AGENT = "ela-data-warehouse-api-key-generator/1.0"
_LOGIN_TIMEOUT_SECONDS = 30
_SMTP_TIMEOUT_SECONDS = 20


class ApiKeyGenerationError(RuntimeError):
    """Edmingle did not return a usable API key."""


class EmailDeliveryError(RuntimeError):
    """The generated API key could not be delivered by email."""


def _required_env(name: str) -> str:
    value = os.getenv(name, "")
    if not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


def extract_api_key(payload: Any) -> str:
    """Validate an Edmingle login response and return the bare key text.

    Callers must not log `payload` or the return value -- either may
    contain the live API key.
    """
    if not isinstance(payload, dict):
        raise ApiKeyGenerationError("Edmingle returned an invalid JSON structure")
    user = payload.get("user")
    api_key = user.get("apikey") if isinstance(user, dict) else None
    if payload.get("code") != 200 or not isinstance(api_key, str) or not api_key.strip():
        message = payload.get("message")
        safe_message = str(message)[:200] if message else "login was not successful"
        raise ApiKeyGenerationError(f"Edmingle rejected the request: {safe_message}")
    api_key = api_key.strip()
    if len(api_key) < 16 or len(api_key) > 256 or any(character.isspace() for character in api_key):
        raise ApiKeyGenerationError("Edmingle returned an API key with an unexpected format")
    return api_key


def generate_api_key() -> str:
    """Make exactly one Edmingle login request. No retry, deliberately --

    this mirrors the legacy script: a login endpoint is not something to
    hammer with backoff/retry logic the way the read-only data endpoints
    are, and a single unambiguous failure is easier for an operator to
    reason about than a masked transient one.
    """
    login_url = _required_env("EDMINGLE_LOGIN_URL")
    if not login_url.startswith("https://"):
        raise ValueError("EDMINGLE_LOGIN_URL must use HTTPS")
    username = _required_env("EDMINGLE_TUTOR_USERNAME")
    password = _required_env("EDMINGLE_TUTOR_PASSWORD")

    login_json = json.dumps({"username": username, "password": password}, separators=(",", ":"))
    session = requests.Session()
    try:
        try:
            response = session.post(
                login_url,
                files={"JSONString": (None, login_json)},
                headers={
                    "Accept": "application/json",
                    "User-Agent": _USER_AGENT,
                },
                timeout=_LOGIN_TIMEOUT_SECONDS,
            )
        except requests.RequestException as error:
            raise ApiKeyGenerationError(
                f"Could not contact Edmingle: {type(error).__name__}"
            ) from error

        if response.status_code == 429:
            # No retry on rate-limit -- a single shot only, per module docstring.
            raise ApiKeyGenerationError("Edmingle rate-limited the login request; try again later")

        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError) as error:
            raise ApiKeyGenerationError(
                f"Edmingle returned HTTP {response.status_code} with invalid JSON"
            ) from error

        if not 200 <= response.status_code < 300:
            message = payload.get("message") if isinstance(payload, dict) else None
            safe_message = str(message)[:200] if message else "request failed"
            raise ApiKeyGenerationError(
                f"Edmingle returned HTTP {response.status_code}: {safe_message}"
            )
        return extract_api_key(payload)
    finally:
        session.close()


def _build_email(api_key: str, generated_at: datetime) -> tuple[str, str]:
    timestamp = generated_at.astimezone()
    subject = "[ELA Data Warehouse] New Edmingle API Key Generated"
    body = "\n".join(
        [
            "A new Edmingle API key was generated successfully.",
            "",
            f"Generated at : {timestamp.strftime('%Y-%m-%d %H:%M:%S %Z')}",
            f"API key      : {api_key}",
            "",
            "This key was not logged or stored anywhere by the data warehouse;",
            "this email is the only record of its value outside Edmingle itself.",
        ]
    )
    return subject, body


def send_api_key_email(api_key: str, generated_at: datetime | None = None) -> None:
    """Send the key once. Raise on any failure instead of swallowing it.

    This deliberately differs from the silent-catch-and-continue philosophy
    used by other collectors in this repo: the entire point of this run is
    to deliver the key to an operator, so a delivery failure must surface
    as a hard error rather than a quiet log line.
    """
    smtp_host = _required_env("SMTP_HOST")
    smtp_port = int(_required_env("SMTP_PORT"))
    from_email = _required_env("SMTP_FROM_EMAIL")
    app_password = _required_env("SMTP_APP_PASSWORD")
    recipients = [item.strip() for item in _required_env("SMTP_TO_EMAILS").split(",") if item.strip()]
    if not recipients:
        raise ValueError("SMTP_TO_EMAILS must list at least one recipient")

    subject, body = _build_email(api_key, generated_at or datetime.now(UTC))
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = from_email
    message["To"] = ", ".join(recipients)
    message.set_content(body)

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(smtp_host, smtp_port, timeout=_SMTP_TIMEOUT_SECONDS) as smtp:
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
            smtp.login(from_email, app_password)
            smtp.send_message(message, from_addr=from_email, to_addrs=recipients)
    except (OSError, smtplib.SMTPException) as error:
        raise EmailDeliveryError(f"Email delivery failed: {type(error).__name__}") from error


def generate_and_deliver_api_key() -> None:
    """Generate one Edmingle API key, email it, and record generation metadata.

    The key text is held in the local `api_key` variable only for the
    interval between the login call and the email send below, is passed
    directly into `send_api_key_email`, and is never passed to `LOGGER`,
    `print`, or any repository/database call. The metadata recorded to
    `system.api_credentials` via `CredentialMetadataRepository.upsert_edmingle`
    carries only `expires_at`/`status` -- Edmingle's login response does not
    include an expiry, so `expires_at` stays `None` ("unknown") rather than
    being guessed.
    """
    LOGGER.info("generating new Edmingle API key")
    generated_at = datetime.now(UTC)

    api_key = generate_api_key()
    try:
        send_api_key_email(api_key, generated_at)
    finally:
        # Drop the only in-memory reference to the key as soon as it has
        # been handed to the mail step, whether or not that step succeeded.
        api_key = None

    database = Database(DatabaseSettings.from_environment(), "api-key-generate")
    try:
        CredentialMetadataRepository(database).upsert_edmingle(
            expires_at=None,
            status="unknown",
        )
    finally:
        database.close()

    LOGGER.info("new Edmingle API key generated and emailed; key was not logged or stored")


if __name__ == "__main__":
    generate_and_deliver_api_key()
