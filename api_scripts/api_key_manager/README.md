# API Key Manager

The current milestone reads the active API key from the runtime secret environment and enforces its configured expiry and pre-expiry stop window. Production collection is refused when expiry metadata is absent, the key has expired, or the renewal window has begun.

API key values must never be stored in PostgreSQL, logs, audit events, YAML, or Git.

This folder is infrastructure that predates the six-legacy-folder port and isn't tied to any single one of those source folders, so it stays here rather than moving under `edmingle_api_key_generator/` (which holds the *generation* logic ported specifically from that legacy folder -- see `../edmingle_api_key_generator/README.md`). `lifecycle.py`'s behavior is unchanged by that port.
