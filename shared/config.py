from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigurationError(ValueError):
    """Raised when required runtime configuration is missing or invalid."""


def _text(name: str, default: str | None = None, *, required: bool = False) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        if required:
            raise ConfigurationError(f"{name} is required")
        return "" if default is None else default
    return value.strip()


def _integer(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if value < minimum or value > maximum:
        raise ConfigurationError(f"{name} must be between {minimum} and {maximum}")
    return value


def _float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be numeric") from exc
    if value < minimum or value > maximum:
        raise ConfigurationError(f"{name} must be between {minimum} and {maximum}")
    return value


def _boolean(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be true or false")


@dataclass(frozen=True)
class DatabaseSettings:
    host: str
    port: int
    name: str
    user: str
    password: str
    sslmode: str
    connect_timeout_seconds: int
    statement_timeout_ms: int
    pool_min_connections: int
    pool_max_connections: int

    @classmethod
    def from_environment(cls) -> DatabaseSettings:
        pool_min = _integer("WAREHOUSE_DB_POOL_MIN_CONNECTIONS", 1, minimum=1, maximum=10)
        pool_max = _integer("WAREHOUSE_DB_POOL_MAX_CONNECTIONS", 4, minimum=1, maximum=20)
        if pool_max < pool_min:
            raise ConfigurationError(
                "WAREHOUSE_DB_POOL_MAX_CONNECTIONS must be >= WAREHOUSE_DB_POOL_MIN_CONNECTIONS"
            )
        sslmode = _text("WAREHOUSE_DB_SSLMODE", "prefer")
        if sslmode not in {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}:
            raise ConfigurationError("WAREHOUSE_DB_SSLMODE is invalid")
        database_name = _text("WAREHOUSE_DB_NAME", required=True)
        if database_name == "webhook_db":
            raise ConfigurationError(
                "WAREHOUSE_DB_NAME must be separate from the production webhook_db database"
            )
        return cls(
            host=_text("WAREHOUSE_DB_HOST", required=True),
            port=_integer("WAREHOUSE_DB_PORT", 5432, minimum=1, maximum=65535),
            name=database_name,
            user=_text("WAREHOUSE_DB_USER", required=True),
            password=_text("WAREHOUSE_DB_PASSWORD", required=True),
            sslmode=sslmode,
            connect_timeout_seconds=_integer(
                "WAREHOUSE_DB_CONNECT_TIMEOUT_SECONDS", 5, minimum=1, maximum=60
            ),
            statement_timeout_ms=_integer(
                "WAREHOUSE_DB_STATEMENT_TIMEOUT_MS", 30000, minimum=500, maximum=600000
            ),
            pool_min_connections=pool_min,
            pool_max_connections=pool_max,
        )

    def connection_kwargs(self, application_name: str) -> dict[str, object]:
        return {
            "host": self.host,
            "port": self.port,
            "dbname": self.name,
            "user": self.user,
            "password": self.password,
            "sslmode": self.sslmode,
            "connect_timeout": self.connect_timeout_seconds,
            "application_name": application_name,
            "options": f"-c statement_timeout={self.statement_timeout_ms}",
        }


@dataclass(frozen=True)
class WarehouseSettings:
    environment: str
    log_level: str
    data_directory: Path
    log_directory: Path
    minimum_free_disk_mb: int
    scheduler_enabled: bool
    scheduler_config: Path

    @classmethod
    def from_environment(cls) -> WarehouseSettings:
        environment = _text("WAREHOUSE_ENVIRONMENT", "development").lower()
        if environment not in {"development", "test", "staging", "production"}:
            raise ConfigurationError("WAREHOUSE_ENVIRONMENT is invalid")
        log_level = _text("WAREHOUSE_LOG_LEVEL", "INFO").upper()
        if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ConfigurationError("WAREHOUSE_LOG_LEVEL is invalid")
        return cls(
            environment=environment,
            log_level=log_level,
            data_directory=Path(_text("WAREHOUSE_DATA_DIRECTORY", "/app/data")),
            log_directory=Path(_text("WAREHOUSE_LOG_DIRECTORY", "/app/logs")),
            minimum_free_disk_mb=_integer(
                "WAREHOUSE_MIN_FREE_DISK_MB", 20480, minimum=512, maximum=1048576
            ),
            scheduler_enabled=_boolean("WAREHOUSE_SCHEDULER_ENABLED", False),
            scheduler_config=Path(
                _text("WAREHOUSE_SCHEDULER_CONFIG", "/app/platform/scheduler/jobs.example.yaml")
            ),
        )


@dataclass(frozen=True)
class EdmingleSettings:
    base_url: str
    api_key: str
    api_key_expires_at: str
    api_key_stop_days_before_expiry: int
    organization_id: str
    institute_id: str
    request_timeout_seconds: int
    max_retries: int
    minimum_request_interval_seconds: float
    batches_per_page: int = 100
    students_per_page: int = 100
    initial_retry_delay_seconds: float = 5.0
    maximum_retry_delay_seconds: float = 300.0

    @classmethod
    def from_environment(cls) -> EdmingleSettings:
        return cls(
            base_url=_text(
                "EDMINGLE_API_BASE_URL", "https://vyoma-api.edmingle.com/nuSource/api/v1"
            ).rstrip("/"),
            api_key=_text("EDMINGLE_API_KEY", required=True),
            api_key_expires_at=_text("EDMINGLE_API_KEY_EXPIRES_AT", ""),
            api_key_stop_days_before_expiry=_integer(
                "EDMINGLE_API_KEY_STOP_DAYS_BEFORE_EXPIRY", 3, minimum=1, maximum=14
            ),
            organization_id=_text("EDMINGLE_ORGANIZATION_ID", required=True),
            institute_id=_text("EDMINGLE_INSTITUTE_ID", ""),
            request_timeout_seconds=_integer(
                "EDMINGLE_REQUEST_TIMEOUT_SECONDS", 60, minimum=5, maximum=300
            ),
            max_retries=_integer("EDMINGLE_MAX_RETRIES", 4, minimum=1, maximum=10),
            minimum_request_interval_seconds=_float(
                "EDMINGLE_MIN_REQUEST_INTERVAL_SECONDS", 2.5, minimum=0.0, maximum=60.0
            ),
            batches_per_page=_integer(
                "EDMINGLE_BATCHES_PER_PAGE", 100, minimum=1, maximum=1000
            ),
            students_per_page=_integer(
                "EDMINGLE_STUDENTS_PER_PAGE", 100, minimum=1, maximum=1000
            ),
            initial_retry_delay_seconds=_float(
                "EDMINGLE_INITIAL_RETRY_DELAY_SECONDS", 5.0, minimum=0.1, maximum=60.0
            ),
            maximum_retry_delay_seconds=_float(
                "EDMINGLE_MAXIMUM_RETRY_DELAY_SECONDS", 300.0, minimum=1.0, maximum=1800.0
            ),
        )

    def redacted_summary(self) -> dict[str, object]:
        return {
            "base_url": self.base_url,
            "organization_id_configured": bool(self.organization_id),
            "institute_id_configured": bool(self.institute_id),
            "api_key_configured": bool(self.api_key),
            "api_key_expires_at": self.api_key_expires_at or None,
            "api_key_stop_days_before_expiry": self.api_key_stop_days_before_expiry,
            "request_timeout_seconds": self.request_timeout_seconds,
            "max_retries": self.max_retries,
            "minimum_request_interval_seconds": self.minimum_request_interval_seconds,
            "batches_per_page": self.batches_per_page,
            "students_per_page": self.students_per_page,
            "initial_retry_delay_seconds": self.initial_retry_delay_seconds,
            "maximum_retry_delay_seconds": self.maximum_retry_delay_seconds,
        }
