from __future__ import annotations

from dataclasses import dataclass


class WarehouseSyncNotConfigured(RuntimeError):
    """Raised when a warehouse sync operation is requested before configuration exists."""


@dataclass(frozen=True)
class WarehouseSyncConfig:
    source_table: str = "public.webhook_events"
    target_table: str = "bronze.webhook_events"
    enabled: bool = False


class WarehouseSyncInterface:
    """Boundary for copying webhook_db events into the data warehouse Bronze layer.

    The production webhook database and the warehouse database are verified as
    separate systems. This interface intentionally avoids guessed credentials,
    mappings, and Silver behavior until the warehouse database is verified.
    """

    def __init__(self, config: WarehouseSyncConfig) -> None:
        self._config = config

    def run_once(self) -> None:
        if not self._config.enabled:
            raise WarehouseSyncNotConfigured("warehouse synchronization is not configured")
        raise WarehouseSyncNotConfigured("warehouse synchronization mappings require verification")
