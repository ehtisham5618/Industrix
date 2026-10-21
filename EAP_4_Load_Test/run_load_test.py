"""EAP-4 CLI: continuous load test + service memory profile against the real IndustriX API.

  python -m EAP_4_Load_Test.run_load_test --profile smoke --target-url http://127.0.0.1:8000
  python -m EAP_4_Load_Test.run_load_test --profile six-hour --target-url http://127.0.0.1:8000 --confirm-long-run
  python -m EAP_4_Load_Test.run_load_test --analyze reports/eap4/runs/<run_id>

Exit codes: 0 PASS/NOT_VERIFIED, 1 FAIL, 2 INTERRUPTED, 3 configuration/target error.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import signal
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import analysis
from .config import PROFILES, ROOT, LoadTestConfig, build_config
from .loadgen import LoadGenerator
from .metrics import RequestMetrics
from .profiler import ServiceProfiler, find_listening_pid
from .report import write_markdown

RUNS = ROOT / "reports" / "eap4" / "runs"
LONG_RUN_SECONDS = 3600


def keep_awake(enable: bool):
    """Temporary thread-scoped Windows sleep inhibition (mirrors ESE-CPU3); cleared in finally."""
    if platform.system() != "Windows":
        return None
    import ctypes
    flags = 0x80000000 | (0x00000001 if enable else 0)
    if not ctypes.windll.kernel32.SetThreadExecutionState(flags):
        raise RuntimeError("Unable to set temporary Windows system-awake request")
    return "SetThreadExecutionState ES_CONTINUOUS | ES_SYSTEM_REQUIRED"


def check_target(cfg: LoadTestConfig) -> dict:
    with urllib.request.urlopen(cfg.target_url + cfg.health_endpoint, timeout=cfg.request_timeout_seconds) as r:
        health = json.loads(r.read(1 << 16))
    if not health.get("model_loaded"):
        raise RuntimeError(f"target {cfg.target_url} reports no model loaded: {health}")
    return health


def environment(cfg: LoadTestConfig, health: dict) -> dict:
    import psutil
    env = dict(python=platform.python_version(), platform=platform.platform(), processor=platform.processor(),
               logical_cpus=psutil.cpu_count(), physical_cpus=psutil.cpu_count(logical=False),
               total_memory_bytes=psutil.virtual_memory().total, target_health=health)
    try:
        import subprocess
        env["git_commit"] = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    except OSError:
        env["git_commit"] = None
    return env


def build_summary(cfg, run_id, started_wall, start_mono, end_mono, completed, interrupted_reason, metrics,
                  profiler_status, env, samples_path, generator=None) -> dict:
    actual = max(0.0, end_mono - start_mono)
    rows, bad = analysis.read_samples(samples_path)
    memory = analysis.memory_analysis(rows, cfg, actual, completed)
    resources = analysis.resource_growth(rows, cfg, actual)
    steady_elapsed = max(0.0, actual - cfg.warmup_seconds)
    steady = metrics.steady.summary(steady_elapsed or None)
    t = cfg.thresholds
    gates = [dict(name="run_completed", status="PASS" if completed else "NOT_VERIFIED",
                  reason=f"{actual:.0f}s of {cfg.duration_seconds:.0f}s" + (f"; {interrupted_reason}" if interrupted_reason else "")),
             memory["drift_gate"], memory["ceiling_gate"],
             dict(name="service_restarts", status="PASS" if not profiler_status["restarts"] else "FAIL",
                  restarts=len(profiler_status["restarts"])),
             dict(name="telemetry_continuity", status="PASS" if not profiler_status["gaps"] and profiler_status["samples"] else "FAIL",
                  gaps=len(profiler_status["gaps"]), sampling_failures=profiler_status["sampling_failures"]),
             analysis.count_gate("handle_or_fd_growth", (resources.get("handles") or resources.get("fds") or {}).get("growth"), t.max_fd_growth),
             analysis.count_gate("thread_growth", (resources.get("threads") or {}).get("growth"), t.max_thread_growth),
             *analysis.request_gates(steady, cfg)]
    private, private_gates = analysis.private_bytes_gates(rows, cfg, actual, completed, platform.system() == "Windows")
    gates.extend(private_gates)
    trend = memory["trend"]
    if trend.get("leak_suspected"):
        gates.append(dict(name="memory_trend", status="FAIL", reason="sustained growth detected (see trend)"))
    else:
        gates.append(dict(name="memory_trend", status="PASS" if trend.get("evidence_sufficient") and completed else "NOT_VERIFIED",
                          reason=trend.get("reason") or "no sustained growth by the declared criteria"))
    return dict(task_id="EAP-4", run_id=run_id, status=analysis.overall_status(completed, gates),
                run_state="COMPLETED" if completed else "INTERRUPTED", profile=cfg.profile,
                configured_duration_seconds=cfg.duration_seconds, actual_duration_seconds=actual,
                started_at=started_wall, ended_at=datetime.now(timezone.utc).isoformat(),
                full_duration_completed=completed, target=cfg.target_url + cfg.endpoint,
                effective_config=json.loads(cfg.model_dump_json()), max_in_flight_configured=cfg.max_in_flight_requests,
                max_in_flight_observed=generator.max_in_flight_seen if generator else None,
                environment=env, request_metrics=dict(totals=metrics.totals(),
                                                      warmup=metrics.warmup.summary(min(actual, cfg.warmup_seconds) or None),
                                                      steady_state=steady),
                memory_metrics=memory, private_bytes_metrics=private, resource_metrics=resources, profiler=profiler_status,
                corrupt_sample_lines=bad, acceptance_thresholds=json.loads(t.model_dump_json()), checks=gates,
                errors=profiler_status.get("failures_tail", []),
                limitations=["No approved latency/error-rate SLA: those gates report measurements as UNDEFINED_THRESHOLD",
                             "Client-observed latency includes HTTP/multipart overhead on loopback",
                             "Service Python GC/allocation stats are not observable from a separate process",
                             "Memory trend analysis on one run flags sustained growth; it cannot prove absence of a leak",
                             "Physical network disconnection not exercised; offline means loopback-only target"])


def run(cfg: LoadTestConfig, out_dir: Path, skip_health: bool = False,
        stop: Optional[threading.Event] = None) -> tuple[dict, int]:
    """Run one load test; `stop` lets a caller (or test) request a graceful early stop."""
    health = {} if skip_health else check_target(cfg)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{cfg.profile}"
    run_dir = out_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "config.json").write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
    env = environment(cfg, health)
    metrics = RequestMetrics()
    start = time.monotonic()
    end = start + cfg.duration_seconds
    pid = cfg.service_pid or find_listening_pid(cfg.target_url)
    profiler = ServiceProfiler(run_dir / "samples.jsonl", cfg.sample_interval_seconds, cfg.target_url, pid=pid,
                               container=cfg.container, extra=lambda: {"requests_completed": metrics.totals()["attempted"]})
    generator = LoadGenerator(cfg, metrics, start, end)
    stop = stop or threading.Event()
    reason = []

    def on_signal(signum, _frame):
        reason.append(f"signal {signal.Signals(signum).name}")
        stop.set()
    handlers = {s: signal.signal(s, on_signal) for s in (signal.SIGINT, signal.SIGTERM, getattr(signal, "SIGBREAK", signal.SIGINT))}
    started_wall = datetime.now(timezone.utc).isoformat()
    print(f"EAP-4 run {run_id}: profile={cfg.profile} target={cfg.target_url}{cfg.endpoint} "
          f"duration={cfg.duration_seconds:.0f}s concurrency={cfg.concurrency} service_pid={pid} out={run_dir}", flush=True)
    awake = None
    try:
        awake = keep_awake(True)
        profiler.start(start)
        generator.start()
        next_report = start + cfg.report_interval_seconds
        with (run_dir / "intervals.jsonl").open("a", encoding="utf-8") as intervals:
            while not stop.is_set() and time.monotonic() < end:
                stop.wait(max(0.0, min(next_report, end) - time.monotonic()))
                if time.monotonic() >= next_report or stop.is_set() or time.monotonic() >= end:
                    elapsed = time.monotonic() - start
                    window = generator.metrics.take_interval()
                    row = dict(elapsed_s=round(elapsed, 3), **window.summary(cfg.report_interval_seconds))
                    intervals.write(json.dumps(row) + "\n")
                    intervals.flush()
                    partial = build_summary(cfg, run_id, started_wall, start, time.monotonic(), False, "run in progress",
                                            metrics, profiler.status(), env, run_dir / "samples.jsonl", generator)
                    partial["run_state"] = "RUNNING"
                    (run_dir / "summary.partial.json").write_text(json.dumps(partial, indent=2, default=str), encoding="utf-8")
                    print(f"[{elapsed:8.0f}s] attempted={metrics.totals()['attempted']} interval_rps={row['throughput_rps'] or 0:.2f} "
                          f"errors={row['failed']} rss={(profiler.tail[-1].get('rss_bytes') or 0) / 1e6 if profiler.tail else 0:.1f}MB",
                          flush=True)
                    next_report += cfg.report_interval_seconds
    except Exception as exc:  # unexpected harness failure: still write what was measured
        reason.append(f"harness error {type(exc).__name__}: {exc}")
    finally:
        if stop.is_set() and not reason:
            reason.append("stop requested")
        generator.stop()
        generator.join(cfg.request_timeout_seconds + 10)
        finished = time.monotonic()
        profiler.stop()
        if awake:
            keep_awake(False)
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
    completed = not reason and finished - start >= cfg.duration_seconds - cfg.sample_interval_seconds
    summary = build_summary(cfg, run_id, started_wall, start, finished, completed, "; ".join(reason) or None,
                            metrics, profiler.status(), env, run_dir / "samples.jsonl", generator)
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    write_markdown(summary, run_dir / "report.md")
    code = {"PASS": 0, "NOT_VERIFIED": 0, "FAIL": 1, "INTERRUPTED": 2}[summary["status"]]
    print(f"EAP-4 {summary['run_state']} status={summary['status']} actual={summary['actual_duration_seconds']:.0f}s "
          f"drift={summary['memory_metrics'].get('drift_percent')} -> {run_dir / 'summary.json'}", flush=True)
    return summary, code


def analyze(run_dir: Path, evaluate_seconds: Optional[float] = None, stop_reason: Optional[str] = None) -> tuple[dict, int]:
    """Re-analyse a completed or partial run's samples without generating load.

    A run whose harness was terminated leaves only summary.partial.json; samples after its
    recorded duration are ignored so request and memory data cover the same period.
    `evaluate_seconds` additionally evaluates the recorded data against a SHORTER duration
    and writes a separate, explicitly labelled file; it never alters the original result.
    """
    cfg = LoadTestConfig.model_validate_json((run_dir / "config.json").read_text(encoding="utf-8"))
    final = (run_dir / "summary.json").exists()
    previous = json.loads((run_dir / ("summary.json" if final else "summary.partial.json")).read_text(encoding="utf-8"))
    actual = previous["actual_duration_seconds"]
    rows, bad = analysis.read_samples(run_dir / "samples.jsonl")
    clipped = [r for r in rows if r.get("elapsed_s", 0) <= actual]
    completed = bool(previous.get("full_duration_completed"))
    reason = stop_reason or ("" if final else "harness terminated before completion; recovered from summary.partial.json")
    label = "reanalyzed"
    if evaluate_seconds is not None:
        if evaluate_seconds > actual + cfg.report_interval_seconds or evaluate_seconds >= cfg.duration_seconds:
            raise ValueError(f"evaluation duration {evaluate_seconds}s must be shorter than the configured "
                             f"{cfg.duration_seconds}s and covered by the recorded {actual:.0f}s")
        cfg = cfg.model_copy(update=dict(duration_seconds=evaluate_seconds))
        completed = actual >= evaluate_seconds - cfg.sample_interval_seconds
        label = f"evaluated_{int(evaluate_seconds)}s"
    memory = analysis.memory_analysis(clipped, cfg, actual, completed)
    trend = memory["trend"]
    trend_gate = dict(name="memory_trend", status="FAIL" if trend.get("leak_suspected") else
                      ("PASS" if trend.get("evidence_sufficient") and completed else "NOT_VERIFIED"),
                      reason=trend.get("reason") or "no sustained growth by the declared criteria")
    run_gate = dict(name="run_completed", status="PASS" if completed else "NOT_VERIFIED",
                    reason=f"{actual:.0f}s of {cfg.duration_seconds:.0f}s" + (f"; {reason}" if reason and not completed else ""))
    private, private_gates = analysis.private_bytes_gates(
        clipped, cfg, actual, completed, str(previous.get("environment", {}).get("platform", "")).startswith("Windows"))
    replaced = {"run_completed", "memory_drift", "memory_ceiling", "memory_trend",
                "memory_drift_private_bytes", "memory_trend_private_bytes"}
    gates = [run_gate] + [g for g in previous["checks"] if g["name"] not in replaced] + \
            [memory["drift_gate"], memory["ceiling_gate"], trend_gate, *private_gates]
    previous.update(memory_metrics=memory, private_bytes_metrics=private,
                    resource_metrics=analysis.resource_growth(clipped, cfg, actual),
                    checks=gates, status=analysis.overall_status(completed, gates),
                    run_state="COMPLETED" if completed else "INTERRUPTED", full_duration_completed=completed,
                    configured_duration_seconds=cfg.duration_seconds, corrupt_sample_lines=bad,
                    samples_after_recorded_duration_ignored=len(rows) - len(clipped),
                    reanalyzed_at=datetime.now(timezone.utc).isoformat(), source_summary="summary.json" if final else "summary.partial.json")
    if evaluate_seconds is not None:
        original = LoadTestConfig.model_validate_json((run_dir / "config.json").read_text(encoding="utf-8"))
        previous.update(profile=f"{original.profile} run evaluated as a {evaluate_seconds / 3600:g}-hour soak",
                        evaluation=dict(evaluated_duration_seconds=evaluate_seconds,
                                        original_profile=original.profile,
                                        original_configured_duration_seconds=original.duration_seconds,
                                        original_requirement_met=False,
                                        note=f"The {original.duration_seconds:.0f}s configured run was stopped at "
                                             f"{actual:.0f}s; this file evaluates the same samples against "
                                             f"{evaluate_seconds:.0f}s and does NOT satisfy the original duration requirement."))
    (run_dir / f"summary.{label}.json").write_text(json.dumps(previous, indent=2, default=str), encoding="utf-8")
    write_markdown(previous, run_dir / f"report.{label}.md")
    return previous, {"PASS": 0, "NOT_VERIFIED": 0, "FAIL": 1, "INTERRUPTED": 2}[previous["status"]]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--profile", choices=sorted(PROFILES) + ["custom"])
    parser.add_argument("--target-url")
    parser.add_argument("--analyze", type=Path, help="re-analyse an existing run directory (no load)")
    parser.add_argument("--evaluate-duration-seconds", type=float,
                        help="with --analyze: also evaluate against a shorter duration (separate, labelled output)")
    parser.add_argument("--stop-reason", help="with --analyze: why a terminated run stopped")
    for name, kind in (("duration-seconds", float), ("warmup-seconds", float), ("baseline-window-seconds", float),
                       ("end-window-seconds", float), ("request-timeout-seconds", float), ("concurrency", int),
                       ("requests-per-second", float), ("sample-interval-seconds", float), ("report-interval-seconds", float),
                       ("service-pid", int)):
        parser.add_argument(f"--{name}", type=kind)
    parser.add_argument("--container")
    parser.add_argument("--memory-ceiling-bytes", type=int)
    parser.add_argument("--max-error-rate", type=float)
    parser.add_argument("--max-p95-latency-ms", type=float)
    parser.add_argument("--out-dir", type=Path, default=RUNS)
    parser.add_argument("--confirm-long-run", action="store_true", help=f"required for runs >= {LONG_RUN_SECONDS}s")
    args = parser.parse_args(argv)
    if args.analyze:
        summary, code = analyze(args.analyze, args.evaluate_duration_seconds, args.stop_reason)
        print(json.dumps(dict(status=summary["status"], drift=summary["memory_metrics"].get("drift_percent")), indent=1))
        return code
    if not args.profile or not args.target_url:
        parser.error("--profile and --target-url are required (or use --analyze)")
    overrides = {k: getattr(args, k) for k in ("duration_seconds", "warmup_seconds", "baseline_window_seconds",
                                                 "end_window_seconds", "request_timeout_seconds", "concurrency",
                                                 "requests_per_second", "sample_interval_seconds", "report_interval_seconds",
                                                 "service_pid", "container")}
    thresholds = {k: getattr(args, k) for k in ("memory_ceiling_bytes", "max_error_rate", "max_p95_latency_ms")
                  if getattr(args, k) is not None}
    try:
        cfg = build_config(args.profile, args.target_url, **overrides)
        if thresholds:
            cfg = cfg.model_copy(update=dict(thresholds=cfg.thresholds.model_copy(update=thresholds)))
        if cfg.duration_seconds >= LONG_RUN_SECONDS and not args.confirm_long_run:
            parser.error(f"{cfg.duration_seconds:.0f}s run requires --confirm-long-run (prevents accidental long runs)")
        _, code = run(cfg, args.out_dir)
        return code
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"EAP-4 configuration/target error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
