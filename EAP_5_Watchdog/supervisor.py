"""EAP-5 watchdog supervisor: monitors configured services and restarts owned ones safely.

Single-threaded tick loop on a monotonic clock. Health checks are sequential and each is
bounded by its own timeout; restarts are bounded by the per-service RestartPolicy.
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import signal
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import psutil

from .config import (ConfigError, HealthCheck, ServiceConfig, WatchdogConfig, expand, redact_env,
                     resolve_command, resolve_cwd)
from .contracts import HealthResult, ServiceState, ServiceStatus, WatchdogEvent, WatchdogStatus
from .health import check, check_http
from .policy import RestartPolicy
from .process import InstanceLock, ManagedProcess, port_owner

QUIET_STATES = {ServiceState.DISABLED, ServiceState.BLOCKED, ServiceState.CONFIG_ERROR}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ServiceRuntime:
    """Mutable per-service state owned by the supervisor."""

    def __init__(self, cfg: ServiceConfig):
        self.cfg = cfg
        self.policy = RestartPolicy(cfg.restart)
        self.process: Optional[ManagedProcess] = None
        self.state = ServiceState.DISABLED if not cfg.enabled else ServiceState.STOPPED
        self.consecutive_failures = 0
        self.total_checks = 0
        self.total_failures = 0
        self.last_check: Optional[HealthResult] = None
        self.last_success: Optional[float] = None
        self.last_success_at: Optional[str] = None
        self.started_at = 0.0
        self.next_check_at = 0.0
        self.recovery_deadline: Optional[float] = None
        self.healthy_since: Optional[float] = None
        self.next_restart_at: Optional[float] = None
        self.last_restart_reason: Optional[str] = None
        self.last_recovery_outcome: Optional[str] = None
        self.detail: Optional[str] = None


class Watchdog:
    def __init__(self, config: WatchdogConfig, clock: Callable[[], float] = time.monotonic,
                 process_factory: Callable[..., ManagedProcess] = ManagedProcess,
                 http_checker: Callable[[HealthCheck], HealthResult] = check_http,
                 port_probe: Callable[[int], Optional[int]] = port_owner,
                 environ: Optional[dict] = None, console: bool = True):
        self.config, self.clock = config, clock
        self.process_factory, self.http_checker, self.port_probe = process_factory, http_checker, port_probe
        self.environ = dict(os.environ if environ is None else environ)
        self.runtime_dir = Path(expand(config.runtime_dir, self.environ))
        self.status_path = self.runtime_dir / "status.json"
        self.stop_path = self.runtime_dir / "watchdog.stop"
        self.lock = InstanceLock(self.runtime_dir / "watchdog.lock")
        self.events: deque[WatchdogEvent] = deque(maxlen=config.event_buffer)
        self.services = [ServiceRuntime(s) for s in config.services]
        self.stop_event = threading.Event()
        self.started_mono = clock()
        self.started_at = utc_now()
        self.logger = self._logger(console)

    # ---- logging / status -------------------------------------------------------------
    def _logger(self, console: bool) -> logging.Logger:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        logger = logging.getLogger(f"eap5.watchdog.{id(self)}")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        handler = logging.handlers.RotatingFileHandler(self.runtime_dir / "watchdog.jsonl", maxBytes=self.config.log_max_bytes,
                                                       backupCount=self.config.log_backups, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        if console:
            stream = logging.StreamHandler()
            stream.setFormatter(logging.Formatter("%(message)s"))
            logger.addHandler(stream)
        return logger

    def emit(self, event: str, svc: Optional[ServiceRuntime] = None, **fields) -> WatchdogEvent:
        base = dict(ts=utc_now(), monotonic_s=round(self.clock() - self.started_mono, 3), event=event,
                    service=svc.cfg.name if svc else None, state=svc.state.value if svc else None,
                    pid=svc.process.pid if svc and svc.process else None,
                    restart_count_window=svc.policy.in_window(self.clock()) if svc else None)
        record = WatchdogEvent(**{**base, **fields})
        self.events.append(record)
        self.logger.info(record.model_dump_json(exclude_none=True))
        return record

    def _transition(self, svc: ServiceRuntime, state: ServiceState, reason: str, **fields) -> None:
        if svc.state == state:
            return
        previous = svc.state
        svc.state = state
        self.emit("state_change", svc, previous_state=previous.value, reason=reason, **fields)

    def status(self) -> WatchdogStatus:
        now = self.clock()
        try:
            rss = psutil.Process().memory_info().rss
        except psutil.Error:
            rss = None
        services = []
        for s in self.services:
            services.append(ServiceStatus(
                name=s.cfg.name, state=s.state, pid=s.process.pid if s.process and s.process.alive() else None,
                owned=bool(s.process and s.process.alive()), consecutive_failures=s.consecutive_failures,
                total_checks=s.total_checks, total_failures=s.total_failures, last_check=s.last_check,
                last_success_monotonic_s=round(s.last_success - self.started_mono, 3) if s.last_success else None,
                last_success_at=s.last_success_at, restarts_in_window=s.policy.in_window(now),
                total_restarts=s.policy.total, last_restart_reason=s.last_restart_reason,
                last_recovery_outcome=s.last_recovery_outcome,
                next_restart_in_seconds=round(s.next_restart_at - now, 1) if s.next_restart_at else None,
                detail=s.detail))
        return WatchdogStatus(version=self.config.version, watchdog_pid=os.getpid(), started_at=self.started_at,
                              updated_at=utc_now(), uptime_seconds=round(now - self.started_mono, 3),
                              running=not self.stop_event.is_set(), services=services,
                              events_buffered=len(self.events), events_buffer_limit=self.config.event_buffer,
                              owned_processes=sum(1 for s in self.services if s.process and s.process.alive()),
                              watchdog_rss_bytes=rss)

    def write_status(self) -> bool:
        """Atomic status write. On Windows a concurrent reader can briefly lock the target; retry,
        then record the failure and carry on: a status reader must never stop the watchdog."""
        tmp = self.status_path.with_suffix(".tmp")
        try:
            tmp.write_text(self.status().model_dump_json(indent=2), encoding="utf-8")
        except OSError as exc:
            self.emit("status_write_failed", reason=f"{type(exc).__name__}: {exc}"[:300])
            return False
        for attempt in range(5):
            try:
                tmp.replace(self.status_path)
                return True
            except PermissionError as exc:
                last = exc
                time.sleep(0.05 * (attempt + 1))
        self.emit("status_write_failed", reason=f"status file locked by another process: {type(last).__name__}")
        return False

    # ---- process control ---------------------------------------------------------------
    def _start(self, svc: ServiceRuntime, reason: str) -> bool:
        cfg = svc.cfg
        if cfg.port:
            owner = self.port_probe(cfg.port)
            mine = svc.process.pid if svc.process and svc.process.alive() else None
            if owner is not None and owner != mine:
                svc.detail = f"port {cfg.port} is owned by pid {owner}, not by this watchdog; refusing to start a duplicate"
                self._transition(svc, ServiceState.BLOCKED, svc.detail)
                return False
        try:
            command = resolve_command(cfg, self.environ)
            cwd = resolve_cwd(cfg, self.environ)
            env = {k: expand(v, self.environ) for k, v in cfg.env.items()}
            svc.process = self.process_factory(cfg.name, command, cwd, env, self.runtime_dir / "logs",
                                               self.config.child_log_max_bytes)
            pid = svc.process.start()
        except (ConfigError, OSError, RuntimeError) as exc:
            svc.detail = f"start failed: {exc}"[:300]
            self._transition(svc, ServiceState.CONFIG_ERROR, svc.detail)
            self.emit("start_failed", svc, reason=svc.detail, outcome="failed")
            return False
        now = self.clock()
        svc.started_at, svc.next_check_at, svc.healthy_since, svc.detail = now, now, None, None
        self.emit("process_started", svc, reason=reason, outcome="started", pid=pid)
        if cfg.env:
            self.emit("environment_overrides", svc, reason=json.dumps(redact_env(cfg.env)))
        return True

    def _stop(self, svc: ServiceRuntime, reason: str) -> None:
        if svc.process is None:
            return
        pid = svc.process.pid
        try:
            code, mode = svc.process.stop(svc.cfg.stop_timeout_seconds)
            self.emit("process_stopped", svc, reason=reason, outcome=f"{mode}; exit_code={code}", pid=pid)
        except (OSError, psutil.Error, RuntimeError) as exc:
            self.emit("stop_error", svc, reason=f"{reason}: {type(exc).__name__}: {exc}"[:300], outcome="failed", pid=pid)

    def _restart(self, svc: ServiceRuntime, now: float, reason: str) -> None:
        decision = svc.policy.decide(now)
        if decision.action == "circuit_open":
            svc.next_restart_at = now + decision.wait_seconds
            if svc.state != ServiceState.DEGRADED:
                self._transition(svc, ServiceState.DEGRADED, decision.reason)
                self.emit("circuit_open", svc, reason=decision.reason, outcome="restarts_suspended",
                          backoff_seconds=round(decision.wait_seconds, 1))
            return
        if decision.action == "wait":
            svc.next_restart_at = now + decision.wait_seconds
            self._transition(svc, ServiceState.BACKOFF, f"{reason}; next restart in {decision.wait_seconds:.1f}s",
                             backoff_seconds=round(decision.wait_seconds, 1))
            return
        svc.next_restart_at = None
        svc.last_restart_reason = reason
        backoff = svc.policy.backoff()
        self._stop(svc, f"restart: {reason}")
        svc.policy.record_restart(now)
        self.emit("restart_initiated", svc, reason=reason, backoff_seconds=round(backoff, 1))
        if self._start(svc, f"restart: {reason}"):
            svc.recovery_deadline = self.clock() + svc.cfg.restart.recovery_timeout_seconds
            svc.consecutive_failures = 0
            self._transition(svc, ServiceState.RECOVERING, "awaiting verified recovery")

    # ---- monitoring --------------------------------------------------------------------
    def start_all(self) -> None:
        for svc in self.services:
            if svc.cfg.enabled:
                if self._start(svc, "initial start"):
                    self._transition(svc, ServiceState.STARTING, "startup grace period")
            else:
                self.emit("service_disabled", svc)

    def tick(self) -> None:
        now = self.clock()
        for svc in self.services:
            try:
                self._tick_service(svc, now)
            except (OSError, psutil.Error, RuntimeError, ValueError) as exc:  # watchdog-side error, not a service failure
                self.emit("watchdog_error", svc, reason=f"{type(exc).__name__}: {exc}"[:300])

    def _tick_service(self, svc: ServiceRuntime, now: float) -> None:
        if svc.state in QUIET_STATES:
            return
        exited = svc.process is not None and not svc.process.alive()
        if exited and svc.state not in (ServiceState.BACKOFF, ServiceState.DEGRADED):
            self.emit("process_exited", svc, reason=f"exit code {svc.process.exit_code()}", outcome="unexpected_exit")
        if svc.process is not None and svc.process.log_oversized():
            svc.detail = f"child log exceeds {self.config.child_log_max_bytes} bytes; rotated at next restart"
        if svc.state in (ServiceState.BACKOFF, ServiceState.DEGRADED) and svc.next_restart_at and now >= svc.next_restart_at:
            if svc.state == ServiceState.DEGRADED:
                self.emit("circuit_half_open", svc, reason="restart window has capacity again")
            self._restart(svc, now, svc.last_restart_reason or "previous failures")
            return
        if now < svc.next_check_at and not exited:
            return
        svc.next_check_at = now + svc.cfg.interval_seconds
        result = check(svc.cfg.health, None if svc.process is None else not exited, self.http_checker)
        svc.total_checks += 1
        svc.last_check = result
        if result.ok:
            self._on_success(svc, now)
        else:
            self._on_failure(svc, now, result, exited)

    def _on_success(self, svc: ServiceRuntime, now: float) -> None:
        svc.consecutive_failures = 0
        svc.last_success, svc.last_success_at = now, utc_now()
        if svc.state == ServiceState.RECOVERING:
            svc.last_recovery_outcome = "recovered"
            svc.recovery_deadline = None
            self._transition(svc, ServiceState.HEALTHY, "recovery verified by health check", outcome="recovered",
                             health=svc.last_check)
            svc.healthy_since = now
        elif svc.state != ServiceState.HEALTHY:
            reason = "healthy" if svc.state == ServiceState.STARTING else "health restored without restart"
            self._transition(svc, ServiceState.HEALTHY, reason, health=svc.last_check)
            svc.healthy_since = now
            svc.next_restart_at = None
        if svc.healthy_since is not None and now - svc.healthy_since >= svc.cfg.restart.recovery_timeout_seconds:
            svc.policy.record_stable()

    def _on_failure(self, svc: ServiceRuntime, now: float, result: HealthResult, exited: bool) -> None:
        svc.total_failures += 1
        svc.healthy_since = None
        if svc.state == ServiceState.STARTING and not exited and now - svc.started_at < svc.cfg.startup_grace_seconds:
            return  # temporary startup failure inside grace: not counted
        if svc.state == ServiceState.RECOVERING:
            if exited or (svc.recovery_deadline is not None and now >= svc.recovery_deadline):
                svc.last_recovery_outcome = "failed"
                self.emit("recovery_failed", svc, reason=result.detail, outcome="not_recovered", health=result)
                svc.consecutive_failures = svc.cfg.restart.failure_threshold
                self._restart(svc, now, f"recovery failed: {result.detail}")
            return
        svc.consecutive_failures = svc.cfg.restart.failure_threshold if exited else svc.consecutive_failures + 1
        if svc.state == ServiceState.DEGRADED:
            return  # restarts suspended; keep observing until the window frees capacity
        if svc.policy.threshold_reached(svc.consecutive_failures):
            reason = "process exited" if exited else f"{svc.consecutive_failures} consecutive failed checks: {result.detail}"
            self._restart(svc, now, reason)
        else:
            self._transition(svc, ServiceState.UNHEALTHY, f"failed check {svc.consecutive_failures}/"
                             f"{svc.cfg.restart.failure_threshold}: {result.detail}", health=result)

    # ---- lifecycle ---------------------------------------------------------------------
    def shutdown(self, reason: str) -> None:
        self.stop_event.set()
        for svc in reversed(self.services):
            if svc.process is not None and svc.process.alive():
                self._stop(svc, f"watchdog shutdown: {reason}")
            if svc.state not in QUIET_STATES:
                svc.state = ServiceState.STOPPED
        self.emit("watchdog_stopped", reason=reason)
        self.write_status()

    def run(self, max_seconds: Optional[float] = None, install_signals: bool = True) -> int:
        """Foreground loop. Returns 0 on requested stop, 3 if another watchdog holds the lock."""
        from .process import LockError
        try:
            self.lock.acquire()
        except LockError as exc:
            self.logger.error(json.dumps(dict(event="lock_unavailable", reason=str(exc))))
            return 3
        previous = {}
        if install_signals and threading.current_thread() is threading.main_thread():
            for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
                sig = getattr(signal, name, None)
                if sig is not None:
                    previous[sig] = signal.signal(sig, lambda signum, _f: self.stop_event.set())
        self.stop_path.unlink(missing_ok=True)
        reason = "stop requested"
        try:
            self.emit("watchdog_started", reason=f"{len(self.services)} services configured; pid {os.getpid()}")
            self.start_all()
            self.write_status()
            deadline = None if max_seconds is None else self.clock() + max_seconds
            while not self.stop_event.is_set():
                if self.stop_path.exists():
                    reason = "stop file"
                    break
                if deadline is not None and self.clock() >= deadline:
                    reason = "max duration reached"
                    break
                self.tick()
                self.write_status()
                self.stop_event.wait(self.config.tick_seconds)
            else:
                reason = "signal"
        finally:
            self.shutdown(reason)
            self.stop_path.unlink(missing_ok=True)
            self.lock.release()
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            self.close()
        return 0

    def close(self) -> None:
        """Release log file handles (idempotent). Called by run(); call it when using tick() directly."""
        for handler in list(self.logger.handlers):
            handler.close()
            self.logger.removeHandler(handler)
