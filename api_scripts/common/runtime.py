from __future__ import annotations

import logging
import uuid
from typing import Any, Protocol

from api_scripts.common.api_client import EdmingleApiClient
from api_scripts.common.models import CollectorStats, RawRecord
from api_scripts.common.repositories import BronzeRepository

LOGGER = logging.getLogger("warehouse.collector")


class Collector(Protocol):
    name: str
    checkpoint_partition_key: str

    def run(self, runtime: CollectorRuntime, checkpoint: dict[str, Any]) -> None: ...


class CollectorRuntime:
    def __init__(
        self,
        *,
        collector_name: str,
        run_id: uuid.UUID,
        client: EdmingleApiClient,
        bronze: BronzeRepository,
    ) -> None:
        self.collector_name = collector_name
        self.run_id = run_id
        self.client = client
        self.bronze = bronze
        self.stats = CollectorStats()
        self.last_checkpoint: dict[str, Any] = {}

    def commit(
        self,
        records: list[RawRecord],
        checkpoint: dict[str, Any],
        *,
        partition_key: str = "default",
    ) -> int:
        inserted = self.bronze.write_with_checkpoint(
            collector_name=self.collector_name,
            run_id=self.run_id,
            records=records,
            checkpoint=checkpoint,
            partition_key=partition_key,
        )
        self.stats.rows_read += len(records)
        self.stats.rows_written += inserted
        self.last_checkpoint = dict(checkpoint)
        LOGGER.info(
            "collector batch committed",
            extra={
                "collector": self.collector_name,
                "received_records": len(records),
                "inserted_records": inserted,
            },
        )
        return inserted
