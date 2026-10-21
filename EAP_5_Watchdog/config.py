"""Typed EAP-5 watchdog configuration (Pydantic v2).

Commands are argument lists executed with shell=False. Supported placeholders:
`{python}` (the watchdog's interpreter), `{root}` (repository root) and
`{env:NAME}` (required environment variable). Nothing else is expanded.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ROOT = Path(__file__).resolve().parents[1]
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
_ENV_TOKEN = re.compile(r"\{env:([A-Za-z_][A-Za-z0-9_]*)\}")
SECRET_HINTS = ("TOKEN", "SECRET", "PASSWORD", "KEY", "CREDENTIAL", "AUTH")


class ConfigError(ValueError):
    """Raised with an actionable message when configuration cannot be used."""


class HealthCheck(BaseModel):
    """How a service's health is judged. kind=process checks liveness only."""
    model_config = ConfigDict(extra="forbid")
    kind: Literal["http", "process"] = "http"
    url: Optional[str] = None
    expect_status: int = Field(200, ge=100, le=599)
    expect_json_true: Optional[str] = Field(None, description="JSON field that must be true, e.g. model_loaded")
    expect_body: Optional[str] = Field(None, max_length=256, description="exact text body, e.g. 'ok'")
    timeout_seconds: float = Field(5.0, gt=0, le=60)
    max_body_bytes: int = Field(65536, ge=64, le=1 << 20)

    @model_validator(mode="after")
    def http_needs_loopback_url(self):
        if self.kind == "http":
            if not self.url:
                raise ValueError("http health check requires url")
            parsed = urlparse(self.url)
            if parsed.scheme != "http" or parsed.hostname not in LOOPBACK:
                raise ValueError(f"health url must be http on loopback (offline-first): {self.url}")
        return self


class RestartPolicyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    failure_threshold: int = Field(3, ge=1, le=100, description="consecutive failed checks before restart")
    cooldown_seconds: float = Field(10.0, ge=0, le=3600, description="minimum gap between restarts")
    backoff_initial_seconds: float = Field(5.0, ge=0, le=3600)
    backoff_multiplier: float = Field(2.0, ge=1, le=10)
    backoff_max_seconds: float = Field(300.0, ge=0, le=86400)
    max_restarts: int = Field(5, ge=1, le=100, description="restarts allowed per rolling window")
    window_seconds: float = Field(3600.0, gt=0, le=7 * 86400)
    recovery_timeout_seconds: float = Field(120.0, gt=0, le=3600, description="time for a restart to become healthy")

    @model_validator(mode="after")
    def backoff_bounds(self):
        if self.backoff_max_seconds < self.backoff_initial_seconds:
            raise ValueError("backoff_max_seconds must be >= backoff_initial_seconds")
        return self


class ServiceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,40}$")
    enabled: bool = True
    command: list[str] = Field(min_length=1, max_length=64)
    cwd: str = "{root}"
    env: dict[str, str] = Field(default_factory=dict, description="non-secret overrides; values never logged")
    port: Optional[int] = Field(None, ge=1, le=65535, description="refuse to start if another process owns it")
    health: HealthCheck
    interval_seconds: float = Field(10.0, ge=0.2, le=3600)
    startup_grace_seconds: float = Field(60.0, ge=0, le=3600)
    stop_timeout_seconds: float = Field(20.0, gt=0, le=300)
    restart: RestartPolicyConfig = RestartPolicyConfig()

    @field_validator("command")
    @classmethod
    def no_shell_strings(cls, value: list[str]) -> list[str]:
        if any(not part or "\n" in part for part in value):
            raise ValueError("command parts must be non-empty single-line arguments")
        return value


class WatchdogConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str = "eap5-watchdog-v1"
    runtime_dir: str = "{root}/EAP_5_Watchdog/runtime"
    tick_seconds: float = Field(1.0, ge=0.1, le=60)
    event_buffer: int = Field(256, ge=16, le=10000, description="recent events kept in memory")
    log_max_bytes: int = Field(5_000_000, ge=10_000, le=500_000_000)
    log_backups: int = Field(3, ge=1, le=20)
    child_log_max_bytes: int = Field(20_000_000, ge=10_000, le=1_000_000_000)
    services: list[ServiceConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def unique(self):
        names = [s.name for s in self.services]
        ports = [s.port for s in self.services if s.port and s.enabled]
        if len(names) != len(set(names)):
            raise ValueError("service names must be unique")
        if len(ports) != len(set(ports)):
            raise ValueError("enabled services must not share a port")
        return self


def expand(value: str, environ: Optional[dict] = None) -> str:
    """Expand only {python}, {root} and {env:NAME}; anything else is left literal."""
    environ = os.environ if environ is None else environ

    def env_value(match: re.Match) -> str:
        name = match.group(1)
        if name not in environ:
            raise ConfigError(f"environment variable {name} is required by the configuration but not set")
        return environ[name]
    return _ENV_TOKEN.sub(env_value, value.replace("{python}", sys.executable).replace("{root}", str(ROOT)))


def resolve_command(service: ServiceConfig, environ: Optional[dict] = None) -> list[str]:
    command = [expand(part, environ) for part in service.command]
    executable = command[0]
    found = shutil.which(executable) if not Path(executable).is_absolute() else (executable if Path(executable).is_file() else None)
    if not found:
        raise ConfigError(f"[{service.name}] executable not found: {executable}")
    return [found, *command[1:]]


def resolve_cwd(service: ServiceConfig, environ: Optional[dict] = None) -> Path:
    cwd = Path(expand(service.cwd, environ))
    if not cwd.is_dir():
        raise ConfigError(f"[{service.name}] working directory does not exist: {cwd}")
    return cwd


def redact_env(env: dict[str, str]) -> dict[str, str]:
    """Names only for secret-looking keys; values are never logged either way."""
    return {k: "<redacted>" if any(h in k.upper() for h in SECRET_HINTS) else "<set>" for k in env}


def load_config(path: Path) -> WatchdogConfig:
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"watchdog configuration not found: {path}")
    if path.stat().st_size > 256_000:
        raise ConfigError("watchdog configuration exceeds 256 KB")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"configuration is not valid JSON: {exc}") from exc
    return WatchdogConfig.model_validate(data)


def validate_runtime(config: WatchdogConfig, environ: Optional[dict] = None) -> list[str]:
    """Resolve every enabled service's executable, cwd and placeholders; return problems (empty = OK)."""
    problems = []
    for service in config.services:
        if not service.enabled:
            continue
        for check in (resolve_command, resolve_cwd):
            try:
                check(service, environ)
            except ConfigError as exc:
                problems.append(str(exc))
        try:
            [expand(v, environ) for v in service.env.values()]
        except ConfigError as exc:
            problems.append(f"[{service.name}] {exc}")
    return problems
