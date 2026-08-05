from __future__ import annotations

import os
import time
from pathlib import Path


def main() -> int:
    data_directory = Path(os.getenv("WAREHOUSE_DATA_DIRECTORY", "/app/data"))
    heartbeat = data_directory / "scheduler.heartbeat"
    if not heartbeat.exists():
        return 1
    return 0 if time.time() - heartbeat.stat().st_mtime < 120 else 1


if __name__ == "__main__":
    raise SystemExit(main())
