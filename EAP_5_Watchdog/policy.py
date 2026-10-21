"""Restart policy: threshold, cooldown, capped exponential backoff and a rolling restart budget.

Pure logic on an injected monotonic clock so behaviour is deterministic under test.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Optional

from .config import RestartPolicyConfig


@dataclass(frozen=True)
class Decision:
    action: str  # "wait" | "restart" | "circuit_open"
    wait_seconds: float = 0.0
    reason: str = ""


class RestartPolicy:
    def __init__(self, cfg: RestartPolicyConfig):
        self.cfg = cfg
        self.restarts: deque[float] = deque(maxlen=cfg.max_restarts)  # bounded by construction
        self.attempt = 0  # consecutive restarts without a stable recovery
        self.total = 0

    def _prune(self, now: float) -> None:
        while self.restarts and now - self.restarts[0] >= self.cfg.window_seconds:
            self.restarts.popleft()

    def in_window(self, now: float) -> int:
        self._prune(now)
        return len(self.restarts)

    def backoff(self) -> float:
        """Backoff before the next restart: 0 for the first, then initial * multiplier^(n-1), capped."""
        if self.attempt == 0:
            return 0.0
        value = self.cfg.backoff_initial_seconds * self.cfg.backoff_multiplier ** (self.attempt - 1)
        return min(value, self.cfg.backoff_max_seconds)

    def threshold_reached(self, consecutive_failures: int) -> bool:
        return consecutive_failures >= self.cfg.failure_threshold

    def decide(self, now: float) -> Decision:
        """Should a restart happen now? Assumes the failure threshold is already reached."""
        self._prune(now)
        if len(self.restarts) >= self.cfg.max_restarts:
            reset_in = self.cfg.window_seconds - (now - self.restarts[0])
            return Decision("circuit_open", max(0.0, reset_in),
                            f"restart budget exhausted: {len(self.restarts)} in {self.cfg.window_seconds:.0f}s")
        last: Optional[float] = self.restarts[-1] if self.restarts else None
        earliest = 0.0 if last is None else last + max(self.cfg.cooldown_seconds, self.backoff())
        if now < earliest:
            return Decision("wait", earliest - now, "cooldown/backoff")
        return Decision("restart", 0.0, "threshold reached")

    def record_restart(self, now: float) -> None:
        self._prune(now)
        self.restarts.append(now)
        self.attempt += 1
        self.total += 1

    def record_stable(self) -> None:
        """A verified recovery that stayed healthy resets the backoff ladder (not the rolling budget)."""
        self.attempt = 0
