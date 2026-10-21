"""EAP-5 watchdog CLI.

  python -m EAP_5_Watchdog validate [--config PATH]
  python -m EAP_5_Watchdog run      [--config PATH] [--max-seconds N]   # foreground
  python -m EAP_5_Watchdog start    [--config PATH]                     # background (detached)
  python -m EAP_5_Watchdog status   [--config PATH]
  python -m EAP_5_Watchdog stop     [--config PATH] [--timeout S]

Exit codes: 0 ok, 1 validation/stop failure, 2 configuration error, 3 another watchdog is running.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from .config import ROOT, ConfigError, WatchdogConfig, expand, load_config, validate_runtime
from .process import IS_WINDOWS, InstanceLock

DEFAULT_CONFIG = ROOT / "EAP_5_Watchdog" / "configs" / "watchdog.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def model_artifact_problems(config: WatchdogConfig) -> list[str]:
    """Local model files referenced via INDUSTRIX_MODEL_PATH must exist (and match a configured SHA256)."""
    problems = []
    for svc in config.services:
        if not svc.enabled or "INDUSTRIX_MODEL_PATH" not in svc.env:
            continue
        path = Path(expand(svc.env["INDUSTRIX_MODEL_PATH"]))
        path = path if path.is_absolute() else Path(expand(svc.cwd)) / path
        if not path.is_file():
            problems.append(f"[{svc.name}] local model file missing: {path} (weights are not downloaded)")
            continue
        expected = svc.env.get("INDUSTRIX_MODEL_SHA256")
        if expected and _sha256(path) != expected.lower():
            problems.append(f"[{svc.name}] model checksum mismatch for {path}")
    return problems


def cmd_validate(config_path: Path) -> int:
    try:
        config = load_config(config_path)
    except (ConfigError, ValueError) as exc:
        print(f"CONFIG INVALID: {exc}")
        return 2
    problems = validate_runtime(config) + model_artifact_problems(config)
    enabled = [s.name for s in config.services if s.enabled]
    disabled = [s.name for s in config.services if not s.enabled]
    print(f"config {config_path}: {len(config.services)} services; enabled {enabled}; disabled {disabled}")
    for svc in config.services:
        if svc.enabled:
            target = svc.health.url if svc.health.kind == "http" else "process liveness"
            print(f"  - {svc.name}: health {svc.health.kind} {target}; every {svc.interval_seconds}s; "
                  f"threshold {svc.restart.failure_threshold}; max {svc.restart.max_restarts} restarts/"
                  f"{svc.restart.window_seconds:.0f}s; backoff {svc.restart.backoff_initial_seconds}-"
                  f"{svc.restart.backoff_max_seconds}s")
    for problem in problems:
        print(f"  PROBLEM: {problem}")
    print("VALID" if not problems else f"INVALID ({len(problems)} problems)")
    return 0 if not problems else 1


def cmd_run(config_path: Path, max_seconds: float | None) -> int:
    from .supervisor import Watchdog
    try:
        config = load_config(config_path)
    except (ConfigError, ValueError) as exc:
        print(f"CONFIG INVALID: {exc}", file=sys.stderr)
        return 2
    return Watchdog(config).run(max_seconds=max_seconds)


def _runtime(config_path: Path) -> Path:
    return Path(expand(load_config(config_path).runtime_dir))


def cmd_start(config_path: Path) -> int:
    runtime = _runtime(config_path)
    runtime.mkdir(parents=True, exist_ok=True)
    if InstanceLock(runtime / "watchdog.lock")._holder_alive():
        print("watchdog already running; not starting a second instance")
        return 3
    console = (runtime / "watchdog.console.log").open("ab")
    kwargs = dict(cwd=str(ROOT), stdout=console, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, shell=False)
    if IS_WINDOWS:
        # A hidden console of its own lets the watchdog deliver CTRL_BREAK to the children it owns.
        info = subprocess.STARTUPINFO()
        info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        info.wShowWindow = 0  # SW_HIDE
        kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE | subprocess.CREATE_NEW_PROCESS_GROUP
        kwargs["startupinfo"] = info
    else:
        kwargs["start_new_session"] = True
    try:
        process = subprocess.Popen([sys.executable, "-m", "EAP_5_Watchdog", "run", "--config", str(config_path)], **kwargs)
    finally:
        console.close()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            print(f"watchdog exited during startup (code {process.returncode}); see {runtime / 'watchdog.console.log'}")
            return 1
        if (runtime / "status.json").exists() and InstanceLock(runtime / "watchdog.lock")._holder_alive():
            print(f"watchdog started in background (pid {process.pid}); status: python -m EAP_5_Watchdog status")
            return 0
        time.sleep(0.5)
    print("watchdog did not report status within 30 s")
    return 1


def cmd_status(config_path: Path) -> int:
    status_path = _runtime(config_path) / "status.json"
    if not status_path.exists():
        print("no status file; the watchdog has not run with this configuration")
        return 1
    status = json.loads(status_path.read_text(encoding="utf-8"))
    alive = bool(InstanceLock(_runtime(config_path) / "watchdog.lock")._holder_alive())
    print(f"watchdog pid {status['watchdog_pid']} running={status['running'] and alive} uptime {status['uptime_seconds']:.0f}s "
          f"events {status['events_buffered']}/{status['events_buffer_limit']} owned processes {status['owned_processes']}")
    for s in status["services"]:
        print(f"  {s['name']:<10} {s['state']:<12} pid={s['pid']} failures={s['consecutive_failures']} "
              f"restarts_window={s['restarts_in_window']} total_restarts={s['total_restarts']} "
              f"last_ok={s['last_success_at']} last_restart={s['last_restart_reason']} recovery={s['last_recovery_outcome']}")
    return 0


def cmd_stop(config_path: Path, timeout: float) -> int:
    runtime = _runtime(config_path)
    lock = InstanceLock(runtime / "watchdog.lock")
    if not lock._holder_alive():
        print("no running watchdog")
        return 0
    (runtime / "watchdog.stop").write_text(str(os.getpid()), encoding="utf-8")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not lock._holder_alive():
            print("watchdog stopped; owned services shut down")
            return 0
        time.sleep(0.5)
    print(f"watchdog did not stop within {timeout}s (stop file left in place)")
    return 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m EAP_5_Watchdog", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["validate", "run", "start", "status", "stop"])
    parser.add_argument("--config", type=Path, default=Path(os.getenv("INDUSTRIX_WATCHDOG_CONFIG", DEFAULT_CONFIG)))
    parser.add_argument("--max-seconds", type=float)
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args(argv)
    if args.command == "validate":
        return cmd_validate(args.config)
    try:
        if args.command == "run":
            return cmd_run(args.config, args.max_seconds)
        if args.command == "start":
            return cmd_start(args.config)
        if args.command == "status":
            return cmd_status(args.config)
        return cmd_stop(args.config, args.timeout)
    except (ConfigError, ValueError) as exc:
        print(f"CONFIG INVALID: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
