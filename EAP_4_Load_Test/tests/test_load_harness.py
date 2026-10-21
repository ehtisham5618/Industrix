"""EAP-4 harness tests.

Metric/gate tests use SYNTHETIC samples to check calculations only; they are not
performance evidence. Runtime tests use a local stub HTTP server on a random port
(never the real service). The real-service smoke is opt-in via EAP4_TARGET_URL.
"""
import json
import math
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from pydantic import ValidationError

from EAP_4_Load_Test import analysis, run_load_test
from EAP_4_Load_Test.config import PROFILES, LoadTestConfig, Thresholds, build_config
from EAP_4_Load_Test.loadgen import LoadGenerator
from EAP_4_Load_Test.metrics import LatencyHistogram, RequestMetrics
from EAP_4_Load_Test.profiler import ServiceProfiler

GOOD = {"filename": "f.png", "detections": [{"class_id": 8, "class_name": "fire", "confidence": 0.9,
                                             "coordinates": {"x1": 1, "y1": 1, "x2": 10, "y2": 10}}]}


# ---- Configuration ------------------------------------------------------------------
def test_six_hour_profile_defaults_to_21600_seconds():
    cfg = build_config("six-hour", "http://127.0.0.1:8000")
    assert cfg.duration_seconds == 21600 and PROFILES["six-hour"]["duration_seconds"] == 21600
    assert cfg.thresholds.max_memory_drift_percent == 5.0
    assert cfg.thresholds.max_error_rate is None and cfg.thresholds.max_p95_latency_ms is None
    assert cfg.max_in_flight_requests == cfg.concurrency and cfg.offline_mode


@pytest.mark.parametrize("overrides", [dict(duration_seconds=0), dict(duration_seconds=-5), dict(concurrency=0),
                                       dict(concurrency=1000), dict(sample_interval_seconds=0),
                                       dict(request_timeout_seconds=0), dict(request_timeout_seconds=500),
                                       dict(report_interval_seconds=1, sample_interval_seconds=5),
                                       dict(warmup_seconds=100, duration_seconds=120),
                                       dict(fixtures=[Path("missing.png")]), dict(unknown_option=1)])
def test_invalid_configuration_rejected(overrides):
    with pytest.raises((ValidationError, ValueError)):
        build_config("smoke", "http://127.0.0.1:8000", **overrides)


@pytest.mark.parametrize("url", ["", "127.0.0.1:8000", "ftp://127.0.0.1", "http://"])
def test_missing_or_invalid_target_rejected(url):
    with pytest.raises((ValidationError, ValueError)):
        build_config("smoke", url)


def test_offline_mode_refuses_remote_target_and_unknown_profile():
    with pytest.raises(ValidationError, match="loopback"):
        build_config("smoke", "http://example.com:8000")
    assert build_config("smoke", "http://example.com:8000", allow_remote_target=True)
    with pytest.raises(ValueError, match="unknown profile"):
        build_config("weekly", "http://127.0.0.1:8000")


def test_long_run_requires_explicit_confirmation(capsys):
    with pytest.raises(SystemExit):
        run_load_test.main(["--profile", "six-hour", "--target-url", "http://127.0.0.1:9"])
    assert "--confirm-long-run" in capsys.readouterr().err


# ---- Metrics (synthetic) --------------------------------------------------------------
def test_histogram_quantiles_within_declared_error():
    hist, values = LatencyHistogram(), [float(i) for i in range(1, 10001)]
    for v in values:
        hist.add(v)
    for q in (.5, .9, .95, .99):
        exact = values[math.ceil(q * len(values)) - 1]
        assert abs(hist.quantile(q) - exact) / exact <= hist.relative_error + 1e-9
    s = hist.summary()
    assert s["count"] == 10000 and s["max_ms"] == 10000 and abs(s["mean_ms"] - 5000.5) < 1e-6
    with pytest.raises(ValueError):
        hist.add(float("nan"))


def test_p99_withheld_for_small_samples_and_counts():
    m = RequestMetrics()
    for i in range(10):
        m.schedule()
        m.record("success" if i < 7 else "timeout", 100.0 if i < 7 else None, 200 if i < 7 else None, warmup=False)
    s = m.steady.summary(10.0)
    assert (s["attempted"], s["successful"], s["failed"], s["timeouts"]) == (10, 7, 3, 3)
    assert s["error_rate"] == pytest.approx(0.3) and s["throughput_rps"] == pytest.approx(1.0)
    assert s["latency_success"]["p99_ms"] is None and "not reported" in s["latency_success"]["p99_note"]
    assert m.totals() == dict(scheduled=10, attempted=10, successful=7)
    with pytest.raises(ValueError):
        m.record("weird", None, None, False)


def test_warmup_is_separated_from_steady_state():
    m = RequestMetrics()
    m.record("success", 5000.0, 200, warmup=True)
    m.record("success", 100.0, 200, warmup=False)
    assert m.steady.summary(1)["latency_success"]["max_ms"] == 100.0
    assert m.warmup.attempted == 1


# ---- Memory gate (synthetic) ----------------------------------------------------------
def cfg_small(**threshold_overrides):
    return build_config("custom", "http://127.0.0.1:8000", duration_seconds=1000, warmup_seconds=100,
                        baseline_window_seconds=100, end_window_seconds=100, request_timeout_seconds=10,
                        concurrency=1, sample_interval_seconds=10, report_interval_seconds=10,
                        thresholds=Thresholds(**threshold_overrides))


def series(end_value, base=1000.0, step=10, duration=1000, shape=None):
    rows = []
    for i, t in enumerate(range(0, duration + 1, step)):
        value = shape(t) if shape else (base if t < duration - 100 else end_value)
        rows.append(dict(elapsed_s=float(t), rss_bytes=value, process_alive=True, requests_completed=i * 3,
                         threads=20, handles=300))
    return rows


@pytest.mark.parametrize("end,status", [(1049.0, "PASS"), (1050.0, "FAIL"), (1100.0, "FAIL"), (900.0, "PASS")])
def test_drift_gate_is_strict_below_five_percent(end, status):
    mem = analysis.memory_analysis(series(end), cfg_small(), 1000, completed=True)
    assert mem["drift_gate"]["status"] == status
    assert mem["drift_percent"] == pytest.approx((end - 1000) / 1000 * 100)
    assert mem["absolute_drift_bytes"] == pytest.approx(end - 1000)


def test_zero_missing_or_insufficient_baseline_is_not_verified():
    zero = [dict(r, rss_bytes=0) if r["elapsed_s"] < 300 else r for r in series(1000)]
    assert analysis.memory_analysis(zero, cfg_small(), 1000, True)["drift_gate"]["status"] == "NOT_VERIFIED"
    missing = [dict(r, rss_bytes=None) if r["elapsed_s"] < 300 else r for r in series(1000)]
    assert analysis.memory_analysis(missing, cfg_small(), 1000, True)["drift_gate"]["status"] == "NOT_VERIFIED"
    assert analysis.memory_analysis([], cfg_small(), 1000, True)["drift_gate"]["status"] == "NOT_VERIFIED"
    dead = [dict(r, process_alive=False) for r in series(1000)]
    assert analysis.memory_analysis(dead, cfg_small(), 1000, True)["drift_gate"]["status"] == "NOT_VERIFIED"


def test_peak_and_independent_ceiling_gate():
    rows = series(1000, shape=lambda t: 3000.0 if t == 500 else 1000.0)
    mem = analysis.memory_analysis(rows, cfg_small(memory_ceiling_bytes=2000), 1000, True)
    assert mem["drift_gate"]["status"] == "PASS"  # ends at baseline ...
    assert mem["ceiling_gate"]["status"] == "FAIL" and mem["ceiling_gate"]["first_exceeded_s"] == 500  # ... but peaked
    assert mem["peak_bytes"] == 3000 and mem["peak_elapsed_s"] == 500
    assert analysis.memory_analysis(rows, cfg_small(), 1000, True)["ceiling_gate"]["status"] == "UNDEFINED_THRESHOLD"


def test_interrupted_run_never_passes_drift_or_overall():
    mem = analysis.memory_analysis(series(1000), cfg_small(), 1000, completed=False)
    assert mem["drift_gate"]["status"] == "NOT_VERIFIED" and "interrupted" in mem["drift_gate"]["reason"]
    assert analysis.overall_status(False, [dict(name="x", status="PASS")]) == "INTERRUPTED"


def test_trend_flags_sustained_growth_but_not_flat_noise():
    leaking = analysis.memory_analysis(series(0, shape=lambda t: 1000.0 + t * 0.04), cfg_small(), 1000, True)
    assert leaking["trend"]["leak_suspected"] is True
    assert leaking["drift_gate"]["status"] == "PASS"  # < 5% drift, yet trend still flags the slow leak
    flat = analysis.memory_analysis(series(0, shape=lambda t: 1000.0 + (5 if (t // 10) % 2 else -5)), cfg_small(), 1000, True)
    assert flat["trend"]["leak_suspected"] is False and flat["trend"]["evidence_sufficient"]
    short = analysis.memory_analysis(series(1000, duration=150, step=10), cfg_small(), 150, True)
    assert short["trend"]["evidence_sufficient"] is False and short["trend"]["leak_suspected"] is None


def test_private_bytes_catch_leak_hidden_by_working_set_trim():
    # Working set (rss) is trimmed by the OS mid-run while committed memory (vms) creeps up.
    rows = [dict(r, rss_bytes=1000.0 if r["elapsed_s"] < 500 else 800.0, vms_bytes=1000.0 + r["elapsed_s"] * 0.04)
            for r in series(1000)]
    rss = analysis.memory_analysis(rows, cfg_small(), 1000, True)
    assert rss["drift_gate"]["status"] == "PASS" and rss["trend"]["leak_suspected"] is False
    private, gates = analysis.private_bytes_gates(rows, cfg_small(), 1000, True, windows_platform=True)
    assert {g["name"]: g["status"] for g in gates} == {"memory_drift_private_bytes": "PASS",
                                                       "memory_trend_private_bytes": "FAIL"}
    assert "Theil-Sen" in gates[1]["reason"] and private["trend"]["leak_suspected"] is True
    assert analysis.private_bytes_gates(rows, cfg_small(), 1000, True, windows_platform=False) == (None, [])


def test_request_gates_undefined_sla_and_violations():
    steady = dict(error_rate=0.02, latency_success=dict(p95_ms=900.0))
    undefined = analysis.request_gates(steady, cfg_small())
    assert {g["status"] for g in undefined} == {"UNDEFINED_THRESHOLD"}
    strict = analysis.request_gates(steady, cfg_small(max_error_rate=0.01, max_p95_latency_ms=500))
    assert [g["status"] for g in strict] == ["FAIL", "FAIL"]
    loose = analysis.request_gates(steady, cfg_small(max_error_rate=0.05, max_p95_latency_ms=1000))
    assert [g["status"] for g in loose] == ["PASS", "PASS"]
    assert analysis.overall_status(True, undefined + [dict(name="m", status="PASS")]) == "NOT_VERIFIED"
    assert analysis.overall_status(True, [dict(name="m", status="PASS")]) == "PASS"
    assert analysis.overall_status(True, strict) == "FAIL"


def test_truncated_sample_line_is_skipped_and_counted(tmp_path):
    path = tmp_path / "samples.jsonl"
    path.write_text(json.dumps(dict(elapsed_s=0, rss_bytes=1)) + "\n" + '{"elapsed_s": 1, "rss_', encoding="utf-8")
    rows, bad = analysis.read_samples(path)
    assert len(rows) == 1 and bad == 1


# ---- Runtime behaviour against a local stub (not the real service) --------------------------
class Stub:
    def __init__(self, mode="ok", delay=0.0):
        stub = self
        self.mode, self.delay, self.in_flight, self.max_in_flight, self.lock = mode, delay, 0, 0, threading.Lock()

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def _send(self, code, body):
                data = json.dumps(body).encode() if not isinstance(body, bytes) else body
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self._send(200, dict(status="ok", model_loaded=True, classes=12))

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                with stub.lock:
                    stub.in_flight += 1
                    stub.max_in_flight = max(stub.max_in_flight, stub.in_flight)
                try:
                    time.sleep(stub.delay)
                    if stub.mode == "ok":
                        self._send(200, GOOD)
                    elif stub.mode == "500":
                        self._send(500, dict(detail="boom"))
                    elif stub.mode == "malformed":
                        self._send(200, b"not json")
                    elif stub.mode == "bad_contract":
                        self._send(200, dict(filename="f", detections=[dict(class_id=8, class_name="fire", confidence=7)]))
                finally:
                    with stub.lock:
                        stub.in_flight -= 1

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def stub():
    servers = []

    def make(**kwargs):
        servers.append(Stub(**kwargs))
        return servers[-1]
    yield make
    for s in servers:
        s.close()


def drive(url, seconds=1.5, concurrency=3, timeout=1.0):
    cfg = build_config("custom", url, duration_seconds=seconds + 5, warmup_seconds=0, baseline_window_seconds=1,
                       end_window_seconds=1, request_timeout_seconds=timeout, concurrency=concurrency,
                       sample_interval_seconds=1, report_interval_seconds=1)
    metrics = RequestMetrics()
    start = time.monotonic()
    gen = LoadGenerator(cfg, metrics, start, start + seconds)
    gen.start()
    assert gen.join(seconds + timeout + 10)
    return gen, metrics.steady.summary(seconds)


def test_concurrency_is_bounded_and_successes_counted(stub):
    s = stub(delay=0.05)
    gen, summary = drive(s.url, concurrency=3)
    assert summary["successful"] > 0 and summary["failed"] == 0
    assert gen.max_in_flight_seen <= 3 and s.max_in_flight <= 3


@pytest.mark.parametrize("mode,outcome", [("500", "http_error"), ("malformed", "invalid_response"),
                                          ("bad_contract", "invalid_response")])
def test_error_and_malformed_responses_classified(stub, mode, outcome):
    _, summary = drive(stub(mode=mode).url, seconds=1.0, concurrency=1)
    assert summary["attempted"] > 0 and summary["outcomes"] == {outcome: summary["attempted"]}
    assert summary["error_rate"] == 1.0


def test_timeouts_and_connection_errors_classified(stub):
    _, slow = drive(stub(delay=1.5).url, seconds=1.0, concurrency=1, timeout=0.3)
    assert slow["timeouts"] >= 1 and slow["successful"] == 0
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]
    # Windows retries SYN to a closed loopback port for ~2 s before refusing; a shorter
    # timeout is (correctly) classified as a timeout, so allow longer than that here.
    _, refused = drive(f"http://127.0.0.1:{closed_port}", seconds=0.5, concurrency=1, timeout=5)
    assert refused["connection_errors"] >= 1 and refused["successful"] == 0


def test_profiler_records_failures_without_raising_and_missing_process(tmp_path):
    def broken():
        raise RuntimeError("sensor exploded")
    prof = ServiceProfiler(tmp_path / "s.jsonl", 0.05, "http://127.0.0.1:9", pid=os.getpid(), extra=broken)
    prof.start()
    time.sleep(0.3)
    prof.stop()
    assert prof.status()["sampling_failures"] >= 1 and "sensor exploded" in prof.status()["failures_tail"][0]["error"]
    nobody = ServiceProfiler(tmp_path / "n.jsonl", 0.05, "http://127.0.0.1:9", pid=None)
    nobody.start(time.monotonic())
    time.sleep(0.2)
    nobody.stop()
    rows, _ = analysis.read_samples(tmp_path / "n.jsonl")
    assert rows and all(r["rss_bytes"] is None and r["process_alive"] is False for r in rows)
    assert "python_gc_tracemalloc" in nobody.unavailable


def test_full_run_persists_partial_and_final_reports(stub, tmp_path):
    s = stub(delay=0.02)
    cfg = build_config("custom", s.url, duration_seconds=6, warmup_seconds=1, baseline_window_seconds=1,
                       end_window_seconds=1, request_timeout_seconds=2, concurrency=2,
                       sample_interval_seconds=0.5, report_interval_seconds=1, service_pid=os.getpid())
    summary, code = run_load_test.run(cfg, tmp_path)
    run_dir = next(tmp_path.iterdir())
    for name in ("config.json", "samples.jsonl", "intervals.jsonl", "summary.partial.json", "summary.json", "report.md"):
        assert (run_dir / name).is_file(), name
    assert summary["run_state"] == "COMPLETED" and summary["full_duration_completed"]
    assert summary["status"] == "NOT_VERIFIED" and code == 0  # undefined SLAs are never a PASS
    assert summary["request_metrics"]["steady_state"]["successful"] > 0
    assert {c["name"] for c in summary["checks"]} >= {"memory_drift", "error_rate", "p95_latency", "run_completed"}
    reanalyzed, _ = run_load_test.analyze(run_dir)
    assert reanalyzed["memory_metrics"]["valid_samples"] == summary["memory_metrics"]["valid_samples"]


def test_interrupted_run_is_reported_as_interrupted_with_partial_data(stub, tmp_path):
    s = stub(delay=0.02)
    cfg = build_config("custom", s.url, duration_seconds=30, warmup_seconds=1, baseline_window_seconds=1,
                       end_window_seconds=1, request_timeout_seconds=2, concurrency=1,
                       sample_interval_seconds=0.5, report_interval_seconds=1, service_pid=os.getpid())
    stop = threading.Event()
    threading.Timer(3, stop.set).start()
    started = time.monotonic()
    summary, code = run_load_test.run(cfg, tmp_path, stop=stop)
    assert time.monotonic() - started < 20
    assert summary["status"] == "INTERRUPTED" and code == 2 and not summary["full_duration_completed"]
    assert summary["actual_duration_seconds"] < 30 and summary["request_metrics"]["totals"]["attempted"] > 0
    assert (next(tmp_path.iterdir()) / "samples.jsonl").stat().st_size > 0
    assert not [t for t in threading.enumerate() if t.name.startswith(("eap4-worker", "eap4-profiler"))]


def test_terminated_run_recovers_from_partial_and_shorter_evaluation_is_labelled(stub, tmp_path):
    s = stub(delay=0.02)
    cfg = build_config("custom", s.url, duration_seconds=8, warmup_seconds=1, baseline_window_seconds=1,
                       end_window_seconds=1, request_timeout_seconds=2, concurrency=1,
                       sample_interval_seconds=0.25, report_interval_seconds=1, service_pid=os.getpid())
    run_load_test.run(cfg, tmp_path)
    run_dir = next(tmp_path.iterdir())
    (run_dir / "summary.json").unlink()  # a hard-killed harness leaves only the partial summary
    partial = json.loads((run_dir / "summary.partial.json").read_text())
    recovered, code = run_load_test.analyze(run_dir, stop_reason="stopped early by decision")
    assert recovered["run_state"] == "INTERRUPTED" and recovered["status"] == "INTERRUPTED" and code == 2
    assert recovered["actual_duration_seconds"] == partial["actual_duration_seconds"]
    assert "stopped early by decision" in recovered["checks"][0]["reason"]
    shorter = partial["actual_duration_seconds"] - 0.5
    evaluated, _ = run_load_test.analyze(run_dir, evaluate_seconds=shorter)
    assert (run_dir / f"summary.evaluated_{int(shorter)}s.json").is_file()
    assert evaluated["configured_duration_seconds"] == shorter and evaluated["full_duration_completed"]
    assert evaluated["evaluation"]["original_requirement_met"] is False
    assert evaluated["evaluation"]["original_configured_duration_seconds"] == 8
    assert json.loads((run_dir / "summary.reanalyzed.json").read_text())["status"] == "INTERRUPTED"  # untouched
    with pytest.raises(ValueError, match="shorter"):
        run_load_test.analyze(run_dir, evaluate_seconds=8)  # cannot claim the original duration


def test_unhealthy_target_rejected_before_load(stub, tmp_path):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    assert run_load_test.main(["--profile", "smoke", "--target-url", f"http://127.0.0.1:{port}",
                               "--out-dir", str(tmp_path)]) == 3
    assert not any(tmp_path.iterdir())


# ---- Real service (opt-in; never during a measured run) ---------------------------------------
@pytest.mark.skipif(not os.getenv("EAP4_TARGET_URL"), reason="set EAP4_TARGET_URL to smoke-test the real service")
def test_real_service_smoke(tmp_path):
    cfg = build_config("smoke", os.environ["EAP4_TARGET_URL"], duration_seconds=40, warmup_seconds=5,
                       baseline_window_seconds=10, end_window_seconds=10, report_interval_seconds=10)
    summary, _ = run_load_test.run(cfg, tmp_path)
    steady = summary["request_metrics"]["steady_state"]
    assert summary["run_state"] == "COMPLETED" and steady["successful"] > 0 and steady["failed"] == 0
    assert summary["memory_metrics"]["valid_samples"] > 0 and summary["environment"]["target_health"]["model_loaded"]
