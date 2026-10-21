"""EAP-4 load-test configuration (Pydantic v2) and named profiles.

Only the task's strict <5% memory-drift gate is an approved threshold. No latency
or error-rate SLA exists for /predict in the repository, so those default to None
(reported as UNDEFINED_THRESHOLD, never PASS).
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURES = (ROOT / "tests/assets/ife_ui3_fire.png", ROOT / "tests/assets/ife_ui3_textile.png")
LOOPBACK = {"127.0.0.1", "localhost", "::1"}


class Thresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_memory_drift_percent: float = Field(5.0, gt=0, description="Strict: drift must be < this (task requirement)")
    memory_ceiling_bytes: Optional[int] = Field(None, gt=0, description="Absolute RSS ceiling; None = undefined")
    max_error_rate: Optional[float] = Field(None, ge=0, le=1, description="None = no approved SLA")
    max_p95_latency_ms: Optional[float] = Field(None, gt=0, description="None = no approved SLA")
    max_fd_growth: Optional[int] = Field(None, ge=0)
    max_thread_growth: Optional[int] = Field(None, ge=0)


class LoadTestConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: Literal["smoke", "short-soak", "six-hour", "custom"]
    target_url: str
    endpoint: str = "/predict"
    health_endpoint: str = "/health"
    duration_seconds: float = Field(gt=0, le=7 * 24 * 3600)
    warmup_seconds: float = Field(ge=0)
    baseline_window_seconds: float = Field(gt=0)
    end_window_seconds: float = Field(gt=0)
    request_timeout_seconds: float = Field(gt=0, le=300)
    concurrency: int = Field(ge=1, le=64)
    requests_per_second: Optional[float] = Field(None, gt=0, le=1000)
    sample_interval_seconds: float = Field(gt=0, le=300)
    report_interval_seconds: float = Field(gt=0)
    seed: int = 42
    fixtures: list[Path] = Field(default_factory=lambda: list(DEFAULT_FIXTURES))
    service_pid: Optional[int] = Field(None, gt=0)
    container: Optional[str] = None
    allow_remote_target: bool = False
    offline_mode: bool = True
    min_samples_per_window: int = Field(3, ge=1)
    thresholds: Thresholds = Thresholds()

    @property
    def max_in_flight_requests(self) -> int:
        # Closed-loop workers: each worker has at most one outstanding request.
        return self.concurrency

    @field_validator("target_url")
    @classmethod
    def http_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("target_url must be an http(s) URL with a host")
        return value.rstrip("/")

    @field_validator("endpoint", "health_endpoint")
    @classmethod
    def absolute_path(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("endpoint paths must start with '/'")
        return value

    @model_validator(mode="after")
    def consistent(self):
        host = urlparse(self.target_url).hostname
        if self.offline_mode and host not in LOOPBACK and not self.allow_remote_target:
            raise ValueError("offline_mode targets must be loopback; pass allow_remote_target to override")
        if self.warmup_seconds + self.baseline_window_seconds + self.end_window_seconds > self.duration_seconds:
            raise ValueError("warmup + baseline window + end window must fit inside duration")
        if self.request_timeout_seconds >= self.duration_seconds:
            raise ValueError("request timeout must be shorter than the run")
        if self.report_interval_seconds < self.sample_interval_seconds:
            raise ValueError("report_interval_seconds must be >= sample_interval_seconds")
        missing = [str(p) for p in self.fixtures if not Path(p).is_file()]
        if not self.fixtures or missing:
            raise ValueError(f"request fixtures missing: {missing or 'none configured'}")
        return self


PROFILES: dict[str, dict] = {
    "smoke": dict(duration_seconds=120, warmup_seconds=20, baseline_window_seconds=30, end_window_seconds=30,
                  request_timeout_seconds=30, concurrency=2, sample_interval_seconds=2, report_interval_seconds=10),
    "short-soak": dict(duration_seconds=1800, warmup_seconds=120, baseline_window_seconds=300, end_window_seconds=300,
                       request_timeout_seconds=30, concurrency=2, sample_interval_seconds=5, report_interval_seconds=60),
    "six-hour": dict(duration_seconds=21600, warmup_seconds=600, baseline_window_seconds=1800, end_window_seconds=1800,
                     request_timeout_seconds=30, concurrency=2, sample_interval_seconds=10, report_interval_seconds=300),
}


def build_config(profile: str, target_url: str, **overrides) -> LoadTestConfig:
    if profile not in PROFILES and profile != "custom":
        raise ValueError(f"unknown profile {profile!r}; choose from {sorted(PROFILES)} or custom")
    values = dict(PROFILES.get(profile, {}))
    values.update({k: v for k, v in overrides.items() if v is not None})
    return LoadTestConfig(profile=profile, target_url=target_url, **values)
