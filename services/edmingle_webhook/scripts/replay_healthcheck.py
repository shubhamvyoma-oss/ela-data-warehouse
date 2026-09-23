from __future__ import annotations

import sys
import time
from pathlib import Path

from app.config.settings import Settings
from scripts.replay_worker import HEARTBEAT_FILENAME

# Generous relative to REPLAY_BACKOFF_SECONDS (default 30s, one full loop
# iteration between heartbeats): 4x the configured backoff, floor 120s, so
# normal timing jitter or one slow run_once() never false-positives this as
# unhealthy.
_STALENESS_MULTIPLIER = 4
_MIN_STALENESS_SECONDS = 120


def main() -> int:
    settings = Settings.from_environment()
    heartbeat = Path(settings.data_directory) / HEARTBEAT_FILENAME
    if not heartbeat.exists():
        # Not yet written on first boot -- give the worker's first loop
        # iteration a chance to run before treating this as unhealthy.
        return 0
    max_age = max(settings.replay_backoff_seconds * _STALENESS_MULTIPLIER, _MIN_STALENESS_SECONDS)
    age = time.time() - heartbeat.stat().st_mtime
    return 0 if age <= max_age else 1


if __name__ == "__main__":
    sys.exit(main())
