from __future__ import annotations

import time
from collections import defaultdict, deque

from app.config.settings import Settings


class InMemoryRateLimiter:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._requests: defaultdict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        if not self._settings.rate_limit_enabled:
            return True
        now = time.time()
        window_start = now - self._settings.rate_limit_window_seconds
        bucket = self._requests[key]
        while bucket and bucket[0] < window_start:
            bucket.popleft()
        if len(bucket) >= self._settings.rate_limit_requests:
            return False
        bucket.append(now)
        return True
