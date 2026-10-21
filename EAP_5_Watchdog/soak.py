"""Watchdog resource soak: the real watchdog (separate process) supervises a disposable service
while failures are injected; the watchdog's own resources are sampled.

python -m EAP_5_Watchdog.soak --duration 3600 --out reports/eap5/soak

Drift = (median RSS over end window - median RSS over baseline window) / baseline * 100, baseline
window starting after warm-up; strict < 5% only with >= 3 valid samples per window. On Windows
private committed bytes (psutil vms) get the same calculation.
"""
from __future__ import annotations

import argparse
import json
import socket
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import psutil

from .config import ROOT

DUMMY = Path(__file__).resolve().parent / "tests" / "dummy_service.py"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def drift(samples: list[dict], key: str, warmup: float, baseline_window: float, end_window: float,
          duration: float) -> dict:
    base = [s[key] for s in samples if warmup <= s["elapsed_s"] < warmup + baseline_window and s.get(key)]
    end = [s[key] for s in samples if s["elapsed_s"] >= duration - end_window and s.get(key)]
    result = dict(metric=key, baseline_samples=len(base), end_samples=len(end), threshold_percent=5.0, comparison="strict <")
    if len(base) < 3 or len(end) < 3:
        return dict(result, status="NOT_VERIFIED", reason="insufficient samples")
    b, e = statistics.median(base), statistics.median(end)
    if b <= 0:
        return dict(result, status="NOT_VERIFIED", reason="invalid baseline")
    pct = (e - b) / b * 100
    from EAP_4_Load_Test.analysis import theil_sen  # same robust slope as EAP-4
    steady = [(s["elapsed_s"] / 3600, s[key]) for s in samples if s["elapsed_s"] >= warmup and s.get(key)]
    slope = theil_sen(steady)
    return dict(result, baseline_bytes=b, end_bytes=e, absolute_drift_bytes=e - b, drift_percent=pct,
                peak_bytes=max(s[key] for s in samples if s.get(key)), theil_sen_bytes_per_hour=slope,
                projected_24h_percent=slope * 24 / b * 100 if slope is not None else None,
                status="PASS" if pct < 5.0 else "FAIL")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=1800)
    parser.add_argument("--sample-interval", type=float, default=5)
    parser.add_argument("--chaos-interval", type=float, default=60, help="seconds between injected failures")
    parser.add_argument("--warmup", type=float, default=120)
    parser.add_argument("--out", type=Path, default=ROOT / "reports" / "eap5" / "soak")
    args = parser.parse_args(argv)
    window = min(600.0, max(30.0, (args.duration - args.warmup) / 4))
    out = args.out.resolve()  # the service runs with cwd=out, so control paths must be absolute
    out.mkdir(parents=True, exist_ok=True)
    control = out / "control"
    control.mkdir(exist_ok=True)
    for name in ("crash", "unhealthy"):
        (control / name).unlink(missing_ok=True)
    port = free_port()
    config = dict(runtime_dir=str(out / "runtime"), tick_seconds=0.5, event_buffer=256,
                  services=[dict(name="soak-service", command=["{python}", str(DUMMY), str(port), str(control)],
                                 cwd=str(out), port=port, health=dict(kind="http", url=f"http://127.0.0.1:{port}/health",
                                                                    expect_json_true="model_loaded", timeout_seconds=2),
                                 interval_seconds=2, startup_grace_seconds=10, stop_timeout_seconds=10,
                                 restart=dict(failure_threshold=2, cooldown_seconds=2, backoff_initial_seconds=2,
                                              backoff_multiplier=2, backoff_max_seconds=8, max_restarts=100,
                                              window_seconds=3600, recovery_timeout_seconds=20))])
    config_path = out / "soak_config.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    log = (out / "watchdog_console.log").open("ab")
    watchdog = subprocess.Popen([sys.executable, "-m", "EAP_5_Watchdog", "run", "--config", str(config_path),
                                 "--max-seconds", str(args.duration + 30)], cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
    proc = psutil.Process(watchdog.pid)
    samples_path = out / "samples.jsonl"
    samples: list[dict] = []
    injected = dict(crash=0, unhealthy=0)
    start = time.monotonic()
    next_chaos = start + args.chaos_interval
    status_path = out / "runtime" / "status.json"
    try:
        with samples_path.open("w", encoding="utf-8") as stream:
            while time.monotonic() - start < args.duration and watchdog.poll() is None:
                now = time.monotonic()
                if now >= next_chaos:
                    kind = "crash" if (injected["crash"] + injected["unhealthy"]) % 2 else "unhealthy"
                    if kind == "unhealthy":
                        (control / "unhealthy").write_text("1")
                        time.sleep(8)  # long enough to cross the failure threshold
                        (control / "unhealthy").unlink(missing_ok=True)
                    else:
                        (control / "crash").write_text("1")
                    injected[kind] += 1
                    next_chaos = now + args.chaos_interval
                try:
                    with proc.oneshot():
                        mem = proc.memory_info()
                        row = dict(elapsed_s=round(time.monotonic() - start, 2), rss_bytes=mem.rss, vms_bytes=mem.vms,
                                   threads=proc.num_threads(), children=len(proc.children(recursive=True)),
                                   cpu_percent=proc.cpu_percent(None))
                        row["handles"] = proc.num_handles() if hasattr(proc, "num_handles") else proc.num_fds()
                except psutil.Error as exc:
                    row = dict(elapsed_s=round(time.monotonic() - start, 2), error=type(exc).__name__)
                try:
                    status = json.loads(status_path.read_text(encoding="utf-8"))
                    svc = status["services"][0]
                    row.update(events_buffered=status["events_buffered"], state=svc["state"],
                               total_restarts=svc["total_restarts"], total_checks=svc["total_checks"])
                except (OSError, ValueError, KeyError, IndexError):
                    pass
                stream.write(json.dumps(row) + "\n")
                stream.flush()
                samples.append(row)
                time.sleep(args.sample_interval)
    finally:
        (control / "unhealthy").unlink(missing_ok=True)
        (out / "runtime" / "watchdog.stop").write_text("soak finished")
        try:
            watchdog.wait(timeout=60)
        except subprocess.TimeoutExpired:
            watchdog.kill()
        log.close()
    duration = samples[-1]["elapsed_s"] if samples else 0.0
    valid = [s for s in samples if "rss_bytes" in s]
    events = [json.loads(line) for line in (out / "runtime" / "watchdog.jsonl").read_text(encoding="utf-8").splitlines() if line]
    summary = dict(
        task="EAP-5", kind="watchdog resource soak", configured_duration_s=args.duration, actual_duration_s=duration,
        completed=duration >= args.duration - 2 * args.sample_interval, warmup_s=args.warmup, window_s=window,
        sample_interval_s=args.sample_interval, samples=len(samples), valid_samples=len(valid),
        injected_failures=injected,
        restarts=max((s.get("total_restarts", 0) for s in samples), default=0),
        health_checks=max((s.get("total_checks", 0) for s in samples), default=0),
        recoveries_verified=sum(1 for e in events if e.get("outcome") == "recovered"),
        recovery_failures=sum(1 for e in events if e.get("event") == "recovery_failed"),
        circuit_opens=sum(1 for e in events if e.get("event") == "circuit_open"),
        events_buffered_max=max((s.get("events_buffered", 0) for s in samples), default=0), events_buffer_limit=256,
        threads=dict(min=min(s["threads"] for s in valid), max=max(s["threads"] for s in valid)) if valid else None,
        handles=dict(first=valid[0]["handles"], last=valid[-1]["handles"], max=max(s["handles"] for s in valid)) if valid else None,
        children_max=max((s["children"] for s in valid), default=None),
        rss=drift(valid, "rss_bytes", args.warmup, window, window, duration),
        private_bytes=drift(valid, "vms_bytes", args.warmup, window, window, duration) if sys.platform == "win32" else None,
        watchdog_exit_code=watchdog.returncode,
        leftover_service_processes=[c.pid for c in psutil.process_iter(["cmdline"])
                                    if c.info.get("cmdline") and str(DUMMY) in " ".join(c.info["cmdline"])],
        limitations=["Watchdog memory only; the supervised service is a disposable stub",
                     f"Duration {duration:.0f}s: not evidence of multi-day stability",
                     "No approved absolute memory ceiling exists"])
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("actual_duration_s", "injected_failures", "restarts", "recoveries_verified",
                                              "events_buffered_max", "leftover_service_processes")}))
    print("RSS:", json.dumps(summary["rss"]))
    if summary["private_bytes"]:
        print("private bytes:", json.dumps(summary["private_bytes"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
