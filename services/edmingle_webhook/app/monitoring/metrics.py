from __future__ import annotations

import threading
import time
from collections import defaultdict


class MetricsRegistry:
    def __init__(self) -> None:
        self._started_at = time.time()
        self._counters: defaultdict[str, int] = defaultdict(int)
        self._gauges: dict[str, float] = {}
        self._latencies: list[float] = []
        self._lock = threading.Lock()

    def increment(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._counters[name] += amount

    def set_gauge(self, name: str, value: float) -> None:
        with self._lock:
            self._gauges[name] = value

    def observe_latency(self, seconds: float) -> None:
        with self._lock:
            self._latencies.append(seconds)
            if len(self._latencies) > 1000:
                self._latencies = self._latencies[-1000:]

    def prometheus(self) -> str:
        with self._lock:
            lines = []
            for name, value in sorted(self._counters.items()):
                lines.append(f"webhook_{name}_total {value}")
            for name, value in sorted(self._gauges.items()):
                lines.append(f"webhook_{name} {value}")
            uptime = int(time.time() - self._started_at)
            avg_latency = sum(self._latencies) / len(self._latencies) if self._latencies else 0
            lines.append(f"webhook_uptime_seconds {uptime}")
            lines.append(f"webhook_average_latency_seconds {avg_latency:.6f}")
            return "\n".join(lines) + "\n"
