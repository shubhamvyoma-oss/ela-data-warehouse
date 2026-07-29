from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigurationError(Exception):
    """Raised when startup configuration is invalid."""


def _read_text(name: str, default: str | None = None, required: bool = False) -> str:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        if required:
            raise ConfigurationError(f"{name} is required")
        return "" if default is None else default
    return value


def _read_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value.strip() == "":
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if value < minimum or value > maximum:
        raise ConfigurationError(f"{name} must be between {minimum} and {maximum}")
    return value


def _read_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value.strip() == "":
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be true or false")


def _read_csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value.strip() == "":
        return default
    values = tuple(value.strip() for value in raw_value.split(",") if value.strip())
    if not values:
        raise ConfigurationError(f"{name} must contain at least one value")
    return values


@dataclass(frozen=True)
class Settings:
    db_name: str
    db_user: str
    db_password: str
    db_host: str
    db_port: int
    db_connect_timeout_seconds: int
    db_statement_timeout_ms: int
    db_pool_min_connections: int
    db_pool_max_connections: int
    db_retry_attempts: int
    db_retry_backoff_ms: int
    webhook_schema_name: str
    webhook_table_name: str
    dedup_enabled: bool
    dedup_table_name: str
    server_host: str
    server_port: int
    total_failure_status: int
    max_payload_bytes: int
    request_timeout_seconds: int
    shared_secret: str
    shared_secret_header: str
    hmac_secret: str
    hmac_signature_header: str
    hmac_timestamp_header: str
    hmac_nonce_header: str
    signature_tolerance_seconds: int
    auth_mode: str
    admin_token: str
    admin_token_header: str
    event_id_fields: tuple[str, ...]
    event_name_fields: tuple[str, ...]
    rate_limit_enabled: bool
    rate_limit_requests: int
    rate_limit_window_seconds: int
    data_directory: Path
    buffer_directory: Path
    processing_directory: Path
    failed_directory: Path
    archive_directory: Path
    log_directory: Path
    log_level: str
    log_json: bool
    log_max_bytes: int
    log_backup_count: int
    disk_min_free_mb: int
    queue_claim_timeout_seconds: int
    replay_batch_size: int
    replay_max_attempts: int
    replay_backoff_seconds: int
    alert_console_enabled: bool
    slack_webhook_url: str
    discord_webhook_url: str
    teams_webhook_url: str

    @classmethod
    def from_environment(cls) -> Settings:
        base_data_dir = Path(_read_text("DATA_DIRECTORY", "/app/data"))
        log_dir = Path(_read_text("LOG_DIRECTORY", "/app/logs"))
        pool_min = _read_int("DB_POOL_MIN_CONNECTIONS", 1, 1, 20)
        pool_max = _read_int("DB_POOL_MAX_CONNECTIONS", 8, 1, 50)
        if pool_max < pool_min:
            raise ConfigurationError("DB_POOL_MAX_CONNECTIONS must be >= DB_POOL_MIN_CONNECTIONS")

        settings = cls(
            db_name=_read_text("DB_NAME", required=True),
            db_user=_read_text("DB_USER", required=True),
            db_password=_read_text("DB_PASSWORD", required=True),
            db_host=_read_text("DB_HOST", required=True),
            db_port=_read_int("DB_PORT", 5432, 1, 65535),
            db_connect_timeout_seconds=_read_int("DB_CONNECT_TIMEOUT_SECONDS", 5, 1, 60),
            db_statement_timeout_ms=_read_int("DB_STATEMENT_TIMEOUT_MS", 5000, 500, 60000),
            db_pool_min_connections=pool_min,
            db_pool_max_connections=pool_max,
            db_retry_attempts=_read_int("DB_RETRY_ATTEMPTS", 2, 1, 5),
            db_retry_backoff_ms=_read_int("DB_RETRY_BACKOFF_MS", 250, 0, 10000),
            webhook_schema_name=_read_text("WEBHOOK_SCHEMA_NAME", "public"),
            webhook_table_name=_read_text("WEBHOOK_TABLE_NAME", "webhook_events"),
            dedup_enabled=_read_bool("WEBHOOK_DEDUP_ENABLED", False),
            dedup_table_name=_read_text("WEBHOOK_DEDUP_TABLE_NAME", "webhook_event_dedup"),
            server_host=_read_text("SERVER_HOST", "0.0.0.0"),
            server_port=_read_int("SERVER_PORT", 5100, 1, 65535),
            total_failure_status=_read_int("WEBHOOK_TOTAL_FAILURE_STATUS", 503, 500, 503),
            max_payload_bytes=_read_int("MAX_PAYLOAD_BYTES", 1048576, 1024, 33554432),
            request_timeout_seconds=_read_int("REQUEST_TIMEOUT_SECONDS", 30, 1, 300),
            shared_secret=_read_text("WEBHOOK_SHARED_SECRET", ""),
            shared_secret_header=_read_text("WEBHOOK_SHARED_SECRET_HEADER", "X-Webhook-Secret"),
            hmac_secret=_read_text("WEBHOOK_HMAC_SECRET", ""),
            hmac_signature_header=_read_text("WEBHOOK_HMAC_SIGNATURE_HEADER", "X-Webhook-Signature"),
            hmac_timestamp_header=_read_text("WEBHOOK_HMAC_TIMESTAMP_HEADER", "X-Webhook-Timestamp"),
            hmac_nonce_header=_read_text("WEBHOOK_HMAC_NONCE_HEADER", "X-Webhook-Nonce"),
            signature_tolerance_seconds=_read_int("WEBHOOK_SIGNATURE_TOLERANCE_SECONDS", 300, 30, 3600),
            auth_mode=_read_text("WEBHOOK_AUTH_MODE", "disabled").lower(),
            admin_token=_read_text("ADMIN_TOKEN", ""),
            admin_token_header=_read_text("ADMIN_TOKEN_HEADER", "X-Admin-Token"),
            event_id_fields=_read_csv("EVENT_ID_FIELDS", ("event_id", "id", "transaction_id", "order_id")),
            event_name_fields=_read_csv("EVENT_NAME_FIELDS", ("event", "event_name", "type")),
            rate_limit_enabled=_read_bool("RATE_LIMIT_ENABLED", True),
            rate_limit_requests=_read_int("RATE_LIMIT_REQUESTS", 120, 1, 100000),
            rate_limit_window_seconds=_read_int("RATE_LIMIT_WINDOW_SECONDS", 60, 1, 3600),
            data_directory=base_data_dir,
            buffer_directory=base_data_dir / "buffer",
            processing_directory=base_data_dir / "buffer" / ".processing",
            failed_directory=base_data_dir / "failed",
            archive_directory=base_data_dir / "archive",
            log_directory=log_dir,
            log_level=_read_text("LOG_LEVEL", "INFO").upper(),
            log_json=_read_bool("LOG_JSON", True),
            log_max_bytes=_read_int("LOG_MAX_BYTES", 10485760, 65536, 268435456),
            log_backup_count=_read_int("LOG_BACKUP_COUNT", 10, 1, 100),
            disk_min_free_mb=_read_int("DISK_MIN_FREE_MB", 100, 1, 1048576),
            queue_claim_timeout_seconds=_read_int("QUEUE_CLAIM_TIMEOUT_SECONDS", 300, 1, 86400),
            replay_batch_size=_read_int("REPLAY_BATCH_SIZE", 100, 1, 10000),
            replay_max_attempts=_read_int("REPLAY_MAX_ATTEMPTS", 10, 1, 100),
            replay_backoff_seconds=_read_int("REPLAY_BACKOFF_SECONDS", 30, 1, 86400),
            alert_console_enabled=_read_bool("ALERT_CONSOLE_ENABLED", True),
            slack_webhook_url=_read_text("SLACK_WEBHOOK_URL", ""),
            discord_webhook_url=_read_text("DISCORD_WEBHOOK_URL", ""),
            teams_webhook_url=_read_text("TEAMS_WEBHOOK_URL", ""),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.webhook_table_name != "webhook_events":
            raise ConfigurationError("WEBHOOK_TABLE_NAME must remain webhook_events")
        if self.webhook_schema_name != "public":
            raise ConfigurationError("WEBHOOK_SCHEMA_NAME must remain public during compatibility phase")
        if self.dedup_table_name != "webhook_event_dedup":
            raise ConfigurationError("WEBHOOK_DEDUP_TABLE_NAME must remain webhook_event_dedup")
        if self.total_failure_status not in {500, 503}:
            raise ConfigurationError("WEBHOOK_TOTAL_FAILURE_STATUS must be 500 or 503")
        if self.auth_mode not in {"disabled", "shared_secret", "hmac"}:
            raise ConfigurationError("WEBHOOK_AUTH_MODE must be disabled, shared_secret, or hmac")
        if self.auth_mode == "shared_secret" and not self.shared_secret:
            raise ConfigurationError("WEBHOOK_SHARED_SECRET is required when WEBHOOK_AUTH_MODE=shared_secret")
        if self.auth_mode == "hmac" and not self.hmac_secret:
            raise ConfigurationError("WEBHOOK_HMAC_SECRET is required when WEBHOOK_AUTH_MODE=hmac")
        if self.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ConfigurationError("LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")
