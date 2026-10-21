"""Bounded request metrics: counts, status codes and a fixed log-bucket latency histogram.

Latency = monotonic time from just before the request is sent to the full response
body being read (client-observed, includes connection reuse/setup). Raw latencies
are never stored: the histogram has fixed memory regardless of run length.
"""
from __future__ import annotations

import bisect
import math
import threading
from collections import Counter
from typing import Optional

_MIN_MS, _MAX_MS, _GROWTH = 0.1, 600_000.0, 1.02
_BOUNDS = [_MIN_MS * _GROWTH ** i for i in range(int(math.log(_MAX_MS / _MIN_MS, _GROWTH)) + 2)]


class LatencyHistogram:
    """Log-bucketed histogram; each bucket spans 2%, so reported quantiles are within ~1%."""

    relative_error = (_GROWTH - 1) / 2

    def __init__(self):
        self.counts = [0] * (len(_BOUNDS) + 1)
        self.n = 0
        self.total = 0.0
        self.minimum = math.inf
        self.maximum = 0.0

    def add(self, ms: float) -> None:
        if not math.isfinite(ms) or ms < 0:
            raise ValueError(f"invalid latency {ms!r}")
        self.counts[bisect.bisect_left(_BOUNDS, ms)] += 1
        self.n += 1
        self.total += ms
        self.minimum = min(self.minimum, ms)
        self.maximum = max(self.maximum, ms)

    def merge(self, other: "LatencyHistogram") -> None:
        for i, c in enumerate(other.counts):
            self.counts[i] += c
        self.n += other.n
        self.total += other.total
        self.minimum = min(self.minimum, other.minimum)
        self.maximum = max(self.maximum, other.maximum)

    def quantile(self, q: float) -> Optional[float]:
        if not 0 <= q <= 1:
            raise ValueError("q must be in [0, 1]")
        if self.n == 0:
            return None
        rank = max(1, math.ceil(q * self.n))
        seen = 0
        for i, c in enumerate(self.counts):
            seen += c
            if seen >= rank:
                low = _BOUNDS[i - 1] if i > 0 else 0.0
                high = _BOUNDS[i] if i < len(_BOUNDS) else self.maximum
                estimate = math.sqrt(max(low, 1e-9) * high) if low > 0 else high
                return min(max(estimate, self.minimum), self.maximum)
        return self.maximum

    def summary(self) -> dict:
        if self.n == 0:
            return dict(count=0)
        out = dict(count=self.n, mean_ms=self.total / self.n, min_ms=self.minimum, max_ms=self.maximum,
                   p50_ms=self.quantile(.5), p90_ms=self.quantile(.9), p95_ms=self.quantile(.95),
                   method=f"fixed log-bucket histogram, relative error <= {self.relative_error:.1%}")
        # p99 needs enough tail observations to be more than the maximum restated.
        out["p99_ms"] = self.quantile(.99) if self.n >= 100 else None
        if out["p99_ms"] is None:
            out["p99_note"] = f"not reported: {self.n} samples < 100"
        return out


class PhaseStats:
    def __init__(self):
        self.latency = LatencyHistogram()
        self.success_latency = LatencyHistogram()
        self.outcomes = Counter()
        self.status_codes = Counter()

    def record(self, outcome: str, latency_ms: Optional[float], status: Optional[int]) -> None:
        self.outcomes[outcome] += 1
        if status is not None:
            self.status_codes[str(status)] += 1
        if latency_ms is not None:
            self.latency.add(latency_ms)
            if outcome == "success":
                self.success_latency.add(latency_ms)

    @property
    def attempted(self) -> int:
        return sum(self.outcomes.values())

    def summary(self, elapsed: Optional[float]) -> dict:
        attempted, ok = self.attempted, self.outcomes["success"]
        return dict(attempted=attempted, successful=ok, failed=attempted - ok,
                    timeouts=self.outcomes["timeout"], connection_errors=self.outcomes["connection_error"],
                    http_errors=self.outcomes["http_error"], invalid_responses=self.outcomes["invalid_response"],
                    outcomes=dict(self.outcomes), status_codes=dict(self.status_codes),
                    error_rate=(attempted - ok) / attempted if attempted else None,
                    throughput_rps=attempted / elapsed if elapsed else None,
                    successful_throughput_rps=ok / elapsed if elapsed else None,
                    latency_all=self.latency.summary(), latency_success=self.success_latency.summary())


class RequestMetrics:
    """Thread-safe recorder split into warm-up and steady-state phases plus a per-interval window."""

    OUTCOMES = ("success", "http_error", "timeout", "connection_error", "invalid_response")

    def __init__(self):
        self._lock = threading.Lock()
        self.warmup = PhaseStats()
        self.steady = PhaseStats()
        self.interval = PhaseStats()
        self.scheduled = 0

    def schedule(self) -> None:
        with self._lock:
            self.scheduled += 1

    def record(self, outcome: str, latency_ms: Optional[float], status: Optional[int], warmup: bool) -> None:
        if outcome not in self.OUTCOMES:
            raise ValueError(f"unknown outcome {outcome!r}")
        with self._lock:
            (self.warmup if warmup else self.steady).record(outcome, latency_ms, status)
            self.interval.record(outcome, latency_ms, status)

    def take_interval(self) -> PhaseStats:
        with self._lock:
            current, self.interval = self.interval, PhaseStats()
        return current

    def totals(self) -> dict:
        with self._lock:
            return dict(scheduled=self.scheduled, attempted=self.warmup.attempted + self.steady.attempted,
                        successful=self.warmup.outcomes["success"] + self.steady.outcomes["success"])
