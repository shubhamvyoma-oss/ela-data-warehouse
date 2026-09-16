# API Key Manager

The current milestone reads the active API key from the runtime secret environment and enforces its configured expiry and pre-expiry stop window. Production collection is refused when expiry metadata is absent, the key has expired, or the renewal window has begun.

Automated monthly generation will be implemented after the key-generation endpoint, authentication contract, and redacted response sample are supplied.

API key values must never be stored in PostgreSQL, logs, audit events, YAML, or Git.


## Automated key generation (`generate.py`)

Automated monthly generation was previously deferred above, pending the key-generation endpoint, authentication contract, and a redacted response sample. That gap is now closed: a legacy standalone script (`edmingle_generate_api_key.py` / `edmingle_api_key_email.py`, already exercised against the real Edmingle login endpoint) supplies the confirmed contract, and it has been ported into `generate.py` per explicit project-owner approval for this port. `lifecycle.py` and its behavior above are unchanged.

`generate.py` provides `generate_and_deliver_api_key()`, which:

1. Makes exactly one `POST` to `EDMINGLE_LOGIN_URL` as multipart form-data (a single `JSONString` field containing the username/password JSON payload) and validates the response. There is no retry -- a login endpoint is not treated like the read-only data endpoints, and a 429 is an immediate error.
2. Emails the generated key to the configured recipients over SMTP (STARTTLS). Email delivery failure **raises** rather than being swallowed -- unlike other jobs in this repo, the entire point of this run is to deliver the key, so the operator must be told if that failed.
3. Records generation metadata via the existing `CredentialMetadataRepository.upsert_edmingle(...)` -- `expires_at=None` / `status="unknown"`, since the login response carries no expiry (never guessed).

**The key value itself is never persisted by this codebase.** It exists only in a local variable between the login call and the email send and is never passed to a logger, `print`, or any database/repository call -- the only place it appears is the outgoing email body. This holds the same line as the rule already stated above: API key values must never be stored in PostgreSQL, logs, audit events, YAML, or Git.

Required environment variables (no credential values are hardcoded):

| Variable | Purpose |
| --- | --- |
| `EDMINGLE_LOGIN_URL` | Edmingle tutor login endpoint (must be HTTPS) |
| `EDMINGLE_TUTOR_USERNAME` | Edmingle login username |
| `EDMINGLE_TUTOR_PASSWORD` | Edmingle login password |
| `SMTP_HOST`, `SMTP_PORT` | SMTP server for delivery |
| `SMTP_FROM_EMAIL`, `SMTP_APP_PASSWORD` | SMTP auth for the sending mailbox |
| `SMTP_TO_EMAILS` | Comma-separated recipient list |

This job authenticates with a username and password, unlike the other API-key-based jobs in this repo, and must only ever be run deliberately by an operator who intends to rotate the key -- never as part of routine/automatic pipeline runs, CI, or tests.

`generate.py` can be run directly (`python3 -m api_scripts.api_key_manager.generate`), which calls `generate_and_deliver_api_key()`. Wiring a dedicated subcommand into `warehouse_cli.py` is a follow-up left for a separate change.
