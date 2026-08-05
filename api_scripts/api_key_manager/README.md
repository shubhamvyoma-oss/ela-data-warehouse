# API Key Manager

The current milestone reads the active API key from the runtime secret environment and enforces its configured expiry and pre-expiry stop window. Production collection is refused when expiry metadata is absent, the key has expired, or the renewal window has begun.

Automated monthly generation will be implemented after the key-generation endpoint, authentication contract, and redacted response sample are supplied.

API key values must never be stored in PostgreSQL, logs, audit events, YAML, or Git.
