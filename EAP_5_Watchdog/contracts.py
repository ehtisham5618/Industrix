"""Typed records emitted by the watchdog (Pydantic v2)."""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ServiceState(str, Enum):
    DISABLED = "disabled"
    STOPPED = "stopped"
    STARTING = "starting"            # within startup grace; failures do not count yet
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"          # failing checks, below the restart threshold
    BACKOFF = "backoff"              # restart due, waiting for cooldown/backoff
    RECOVERING = "recovering"        # restarted; waiting for a successful recovery check
    DEGRADED = "degraded"            # restart budget exhausted (circuit open); still observed
    BLOCKED = "blocked"              # refused to start: e.g. port owned by an unmanaged process
    CONFIG_ERROR = "config_error"


class HealthResult(BaseModel):
    ok: bool
    kind: str
    status_code: Optional[int] = None
    latency_ms: Optional[float] = None
    detail: str = Field("", max_length=300)


class WatchdogEvent(BaseModel):
    """One structured log/event record. `service` is None for watchdog-level events."""
    ts: str
    monotonic_s: float
    event: str
    service: Optional[str] = None
    state: Optional[str] = None
    previous_state: Optional[str] = None
    reason: Optional[str] = Field(None, max_length=500)
    outcome: Optional[str] = None
    pid: Optional[int] = None
    restart_count_window: Optional[int] = None
    backoff_seconds: Optional[float] = None
    health: Optional[HealthResult] = None


class ServiceStatus(BaseModel):
    name: str
    state: ServiceState
    pid: Optional[int] = None
    owned: bool = False
    consecutive_failures: int = 0
    total_checks: int = 0
    total_failures: int = 0
    last_check: Optional[HealthResult] = None
    last_success_monotonic_s: Optional[float] = None
    last_success_at: Optional[str] = None
    restarts_in_window: int = 0
    total_restarts: int = 0
    last_restart_reason: Optional[str] = None
    last_recovery_outcome: Optional[str] = None
    next_restart_in_seconds: Optional[float] = None
    detail: Optional[str] = None


class WatchdogStatus(BaseModel):
    version: str
    watchdog_pid: int
    started_at: str
    updated_at: str
    uptime_seconds: float
    running: bool
    services: list[ServiceStatus]
    events_buffered: int
    events_buffer_limit: int
    owned_processes: int
    watchdog_rss_bytes: Optional[int] = None
