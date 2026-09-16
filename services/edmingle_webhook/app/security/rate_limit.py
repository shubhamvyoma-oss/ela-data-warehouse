from __future__ import annotations

import time
from collections import defaultdict, deque

from app.config.settings import Settings


class InMemoryRateLimiter:
    """Per-process sliding-window rate limiter.

    KNOWN LIMITATION: state lives in plain process memory, not a shared
    store. The Dockerfile runs gunicorn with multiple worker processes
    (currently 2), and each worker holds its own independent counters for
    the same client key. A client's real effective limit is therefore
    roughly (configured RATE_LIMIT_REQUESTS x worker count), not the
    configured value, depending on which worker gunicorn routes each
    request to. This is accepted as a known, documented gap rather than
    fixed with a new external dependency (e.g. Redis) -- see
    docs/architecture.md's Rate Limiting section and the repository-root
    ROADMAP.md.
    """

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
