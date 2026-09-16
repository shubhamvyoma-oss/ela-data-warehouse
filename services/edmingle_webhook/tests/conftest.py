from __future__ import annotations

from pathlib import Path

import pytest

from app.config.settings import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data_dir = tmp_path / "data"
    return Settings(
        db_name="test",
        db_user="test",
        db_password="test",
        db_host="localhost",
        db_port=5432,
        db_connect_timeout_seconds=1,
        db_statement_timeout_ms=1000,
        db_pool_min_connections=1,
        db_pool_max_connections=2,
        db_retry_attempts=1,
        db_retry_backoff_ms=0,
        webhook_schema_name="public",
        webhook_table_name="webhook_events",
        dedup_enabled=False,
        dedup_table_name="webhook_event_dedup",
        server_host="127.0.0.1",
        server_port=5100,
        total_failure_status=503,
        max_payload_bytes=1024,
        request_timeout_seconds=30,
        shared_secret="secret",
        shared_secret_header="X-Webhook-Secret",
        hmac_secret="",
        hmac_signature_header="X-Webhook-Signature",
        hmac_timestamp_header="X-Webhook-Timestamp",
        hmac_nonce_header="X-Webhook-Nonce",
        signature_tolerance_seconds=300,
        auth_mode="shared_secret",
        admin_token="admin",
        admin_token_header="X-Admin-Token",
        event_id_fields=("event_id", "id"),
        event_name_fields=("event", "type"),
        rate_limit_enabled=False,
        rate_limit_requests=120,
        rate_limit_window_seconds=60,
        data_directory=data_dir,
        buffer_directory=data_dir / "buffer",
        processing_directory=data_dir / "buffer" / ".processing",
        failed_directory=data_dir / "failed",
        archive_directory=data_dir / "archive",
        log_directory=tmp_path / "logs",
        log_level="INFO",
        log_json=True,
        log_max_bytes=65536,
        log_backup_count=2,
        disk_min_free_mb=1,
        queue_claim_timeout_seconds=300,
        replay_batch_size=10,
        replay_max_attempts=2,
        replay_backoff_seconds=1,
    )
