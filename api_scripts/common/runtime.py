from __future__ import annotations

import logging
import uuid
from typing import Any, Protocol

from api_scripts.common.api_client import EdmingleApiClient
from api_scripts.common.models import JobStats, RawRecord
from api_scripts.common.repositories import BronzeRepository, TransformedTableRepository

LOGGER = logging.getLogger("warehouse.job")


class Job(Protocol):
    name: str
    checkpoint_partition_key: str

    def run(self, runtime: JobRuntime, checkpoint: dict[str, Any]) -> None: ...


class JobRuntime:
    def __init__(
        self,
        *,
        job_name: str,
        run_id: uuid.UUID,
        client: EdmingleApiClient,
        bronze: BronzeRepository,
        transformed: TransformedTableRepository | None = None,
    ) -> None:
        self.job_name = job_name
        self.run_id = run_id
        self.client = client
        self.bronze = bronze
        self.transformed = transformed
        self.stats = JobStats()
        self.last_checkpoint: dict[str, Any] = {}

    def commit(
        self,
        records: list[RawRecord],
        checkpoint: dict[str, Any],
        *,
        partition_key: str = "default",
    ) -> int:
        inserted = self.bronze.write_with_checkpoint(
            job_name=self.job_name,
            run_id=self.run_id,
            records=records,
            checkpoint=checkpoint,
            partition_key=partition_key,
        )
        self.stats.rows_read += len(records)
        self.stats.rows_written += inserted
        self.last_checkpoint = dict(checkpoint)
        LOGGER.info(
            "job batch committed",
            extra={
                "job": self.job_name,
                "received_records": len(records),
                "inserted_records": inserted,
            },
        )
        return inserted

    def commit_rows(
        self,
        *,
        table: str,
        columns: list[str],
        rows: list[tuple[Any, ...]],
        unique_columns: list[str],
        checkpoint: dict[str, Any],
        partition_key: str = "default",
    ) -> int:
        """Commit already-transformed rows into a ported-pipeline's own Bronze
        table via TransformedTableRepository. Used by every job ported from
        the six legacy script folders; the original four jobs that used
        the raw bronze.edmingle_api_records shape continue to use commit()."""
        if self.transformed is None:
            raise RuntimeError(
                "JobRuntime was constructed without a TransformedTableRepository"
            )
        inserted = self.transformed.write_with_checkpoint(
            table=table,
            columns=columns,
            rows=rows,
            unique_columns=unique_columns,
            job_name=self.job_name,
            run_id=self.run_id,
            checkpoint=checkpoint,
            partition_key=partition_key,
        )
        self.stats.rows_read += len(rows)
        self.stats.rows_written += inserted
        self.last_checkpoint = dict(checkpoint)
        LOGGER.info(
            "job batch committed",
            extra={
                "job": self.job_name,
                "table": table,
                "received_rows": len(rows),
                "inserted_rows": inserted,
            },
        )
        return inserted
