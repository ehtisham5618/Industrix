"""FDD-1 code-freeze release gate: one repeatable command, consolidated JSON + Markdown report.

  python -m FDD_1_Release_Regression.run_release_gate [--baseline-junit PATH] [--skip-live] [--load-seconds N]

Run with the full-stack interpreter (ESE_CPU1_Quantization/runtime/venv). Statuses: PASS, FAIL,
BLOCKED (prerequisite missing), NOT_VERIFIED (insufficient evidence), BASELINE_FAILURE (failed
identically before FDD-1 changes).
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports" / "fdd1"
FIXTURES = [ROOT / "tests/assets/ife_ui3_fire.png", ROOT / "tests/assets/ife_ui3_textile.png"]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(cmd: list[str], log: Path, timeout: float, env: Optional[dict] = None) -> tuple[int, float]:
    started = time.monotonic()
    with log.open("w", encoding="utf-8") as stream:
        try:
            code = subprocess.run(cmd, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout,
                                  env={**os.environ, **(env or {})}).returncode
        except subprocess.TimeoutExpired:
            code = -1
            stream.write(f"\nTIMEOUT after {timeout}s\n")
    return code, time.monotonic() - started


def junit_cases(path: Path) -> dict[str, str]:
    """Map 'classname::name' -> passed/failed/error/skipped."""
    cases = {}
    if not path.is_file():
        return cases
    for case in ET.parse(path).getroot().iter("testcase"):
        key = f"{case.get('classname')}::{case.get('name')}"
        kinds = {child.tag for child in case}
        cases[key] = "failed" if "failure" in kinds else "error" if "error" in kinds else "skipped" if "skipped" in kinds else "passed"
    return cases


def component(key: str) -> str:
    return key.split(".")[0].split("::")[0] or "root"


def stage_tests(baseline: Path, out: Path) -> dict:
    junit = out / "junit_candidate.xml"
    code, seconds = run([sys.executable, "-X", "utf8", "-m", "pytest", "-q", "-rs", "-p", "no:cacheprovider",
                         f"--junitxml={junit}"], out / "pytest_candidate.txt", 3600)
    cand, base = junit_cases(junit), junit_cases(baseline)
    per = defaultdict(Counter)
    for key, status in cand.items():
        per[component(key)][status] += 1
    failures = []
    for key, status in sorted(cand.items()):
        if status in ("failed", "error"):
            before = base.get(key)
            failures.append(dict(test=key, status="BASELINE_FAILURE" if before in ("failed", "error") else "FAIL",
                                 baseline=before or "absent"))
    new_failures = [f for f in failures if f["status"] == "FAIL"]
    fixed = [k for k, s in base.items() if s in ("failed", "error") and cand.get(k) == "passed"]
    totals = Counter(cand.values())
    return dict(name="full_test_suite", component="all", status="FAIL" if new_failures else ("PASS" if not failures else "BASELINE_FAILURE"),
                exit_code=code, duration_s=round(seconds, 1), totals=dict(totals), collected=len(cand),
                baseline_totals=dict(Counter(base.values())), per_component={k: dict(v) for k, v in sorted(per.items())},
                failures=failures, fixed_since_baseline=fixed, log=str((out / "pytest_candidate.txt").relative_to(ROOT)))


def stage_model(out: Path) -> dict:
    report = out / "model_regression_report.json"
    code, seconds = run([sys.executable, "-X", "utf8", "-m", "EAP_2_CI_Model_Regression.runner", "--out", str(report)],
                        out / "model_regression.txt", 1800)
    if not report.is_file():
        return dict(name="model_regression", component="inference", status="BLOCKED", exit_code=code,
                    reason="runner produced no report (model or dataset missing?)")
    data = json.loads(report.read_text(encoding="utf-8"))
    checks = Counter(c["status"] for c in data["checks"])
    status = "FAIL" if data["status"] == "FAIL" else ("BLOCKED" if checks.get("NOT_VERIFIED") and not checks.get("PASS") else
                                                      "PASS" if checks.get("FAIL", 0) == 0 else "FAIL")
    return dict(name="model_regression", component="inference", status=status, exit_code=code, duration_s=round(seconds, 1),
                report_status=data["status"], check_counts=dict(checks), metrics=data.get("metrics", {}).get("measured"),
                delta_pp=data.get("metrics", {}).get("delta_pp"), model_sha256=data.get("model_sha256"),
                note="UNDEFINED_THRESHOLD gates are measurements without an approved tolerance, not failures",
                report=str(report.relative_to(ROOT)))


def http(method: str, url: str, body: Optional[bytes] = None, ctype: Optional[str] = None, timeout: float = 60):
    request = urllib.request.Request(url, data=body, method=method, headers={"Content-Type": ctype} if ctype else {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def multipart(path: Path, data: Optional[bytes] = None) -> tuple[bytes, str]:
    boundary = "fdd1boundary"
    payload = data if data is not None else path.read_bytes()
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
            f"Content-Type: image/png\r\n\r\n").encode() + payload + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def wait_status(runtime: Path, predicate, timeout: float) -> Optional[dict]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            status = json.loads((runtime / "status.json").read_text(encoding="utf-8"))
            if predicate(status):
                return status
        except (OSError, ValueError):
            pass
        time.sleep(2)
    return None


def stage_live(out: Path, load_seconds: float) -> list[dict]:
    """Real backend + dashboard under the EAP-5 watchdog; real requests; EAP-4 smoke load; clean stop."""
    from EAP_2_CI_Model_Regression import gate
    from EAP_5_Watchdog.config import expand, load_config
    config_path = ROOT / "EAP_5_Watchdog/configs/watchdog.json"
    runtime = Path(expand(load_config(config_path).runtime_dir))
    results = []
    watchdog = subprocess.Popen([sys.executable, "-m", "EAP_5_Watchdog", "run", "--config", str(config_path)], cwd=ROOT,
                                stdout=(out / "live_watchdog.txt").open("w"), stderr=subprocess.STDOUT)
    started = time.monotonic()
    try:
        status = wait_status(runtime, lambda s: all(x["state"] == "healthy" for x in s["services"]), 300)
        results.append(dict(name="live_stack_startup", component="watchdog+backend+dashboard",
                            status="PASS" if status else "FAIL", duration_s=round(time.monotonic() - started, 1),
                            detail={x["name"]: x["state"] for x in (status or {}).get("services", [])}))
        if not status:
            return results
        manifest = gate.load_manifest(ROOT / "EAP_2_CI_Model_Regression/baselines/cme-opt2-focal-cosine-12class-v1.json")
        from PIL import Image
        contract = []
        for fixture in FIXTURES:
            code, body = http("POST", "http://127.0.0.1:8000/predict", *multipart(fixture))
            with Image.open(fixture) as image:
                response = gate.validate_response(json.loads(body), manifest.class_map, *image.size) if code == 200 else None
            contract.append(dict(fixture=fixture.name, http=code, detections=len(response.detections) if response else None,
                                 classes=sorted({d.class_name for d in response.detections}) if response else None))
        results.append(dict(name="live_predict_contract", component="backend+inference",
                            status="PASS" if all(c["http"] == 200 and c["detections"] for c in contract) else "FAIL",
                            detail=contract))
        code, body = http("POST", "http://127.0.0.1:8000/predict", *multipart(FIXTURES[0], b"\x89PNG corrupt"))
        results.append(dict(name="live_corrupt_upload", component="backend+preprocessing",
                            status="PASS" if code == 400 else "FAIL", detail=dict(http=code, body=body[:120].decode(errors="replace"))))
        checks = {}
        for name, url in (("health", "http://127.0.0.1:8000/health"), ("system_status", "http://127.0.0.1:8000/system/status"),
                          ("incidents", "http://127.0.0.1:8000/incidents"), ("dashboard", "http://127.0.0.1:8501/_stcore/health")):
            code, body = http("GET", url)
            checks[name] = dict(http=code, bytes=len(body))
        results.append(dict(name="live_service_endpoints", component="backend+incidents+dashboard",
                            status="PASS" if all(v["http"] == 200 for v in checks.values()) else "FAIL", detail=checks))
        code, seconds = run([sys.executable, "-X", "utf8", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                             "FDD_1_Release_Regression/tests/test_release_regression.py::test_dashboard_renders_against_live_backend"],
                            out / "live_dashboard_render.txt", 300, env={"FDD1_BACKEND_URL": "http://127.0.0.1:8000"})
        results.append(dict(name="live_dashboard_render", component="dashboard", status="PASS" if code == 0 else "FAIL",
                            duration_s=round(seconds, 1), log="reports/fdd1/live_dashboard_render.txt"))
        load_dir = out / "load"
        code, seconds = run([sys.executable, "-X", "utf8", "-m", "EAP_4_Load_Test.run_load_test", "--profile", "smoke",
                             "--target-url", "http://127.0.0.1:8000", "--duration-seconds", str(load_seconds),
                             "--out-dir", str(load_dir)], out / "load_smoke.txt", load_seconds + 300)
        summaries = sorted(load_dir.glob("*/summary.json"))
        if summaries:
            s = json.loads(summaries[-1].read_text(encoding="utf-8"))
            steady = s["request_metrics"]["steady_state"]
            mem, pb = s["memory_metrics"], s.get("private_bytes_metrics") or {}
            results.append(dict(name="load_and_memory_smoke", component="backend (resource)",
                                status="FAIL" if steady["failed"] else "NOT_VERIFIED",
                                reason="short smoke: memory stability needs a long soak; no approved latency SLA",
                                detail=dict(duration_s=s["actual_duration_seconds"], attempted=steady["attempted"],
                                            failed=steady["failed"], throughput_rps=steady["throughput_rps"],
                                            p50_ms=steady["latency_success"].get("p50_ms"), p95_ms=steady["latency_success"].get("p95_ms"),
                                            rss_drift_percent=mem.get("drift_percent"), private_bytes_drift_percent=pb.get("drift_percent"),
                                            summary=str(summaries[-1].relative_to(ROOT)))))
        else:
            results.append(dict(name="load_and_memory_smoke", component="backend (resource)", status="FAIL",
                                reason=f"load harness exited {code} without a summary"))
        final = json.loads((runtime / "status.json").read_text(encoding="utf-8"))
        results.append(dict(name="no_unexpected_restarts_during_gate", component="watchdog",
                            status="PASS" if all(x["total_restarts"] == 0 for x in final["services"]) else "FAIL",
                            detail={x["name"]: x["total_restarts"] for x in final["services"]}))
    finally:
        (runtime / "watchdog.stop").write_text("fdd1 gate finished", encoding="utf-8")
        try:
            watchdog.wait(timeout=120)
        except subprocess.TimeoutExpired:
            watchdog.kill()
    freed = {port: _port_free(port) for port in (8000, 8501)}
    results.append(dict(name="clean_shutdown", component="watchdog", status="PASS" if watchdog.returncode == 0 and all(freed.values()) else "FAIL",
                        detail=dict(watchdog_exit=watchdog.returncode, ports_free=freed)))
    return results


def _port_free(port: int) -> bool:
    import socket
    with socket.socket() as probe:
        return probe.connect_ex(("127.0.0.1", port)) != 0


def overall(stages: list[dict]) -> str:
    statuses = {s["status"] for s in stages}
    if "FAIL" in statuses:
        return "FAIL"
    if statuses & {"BLOCKED", "NOT_VERIFIED", "BASELINE_FAILURE"}:
        return "PASS_WITH_EXCEPTIONS"
    return "PASS"


def markdown(report: dict) -> str:
    lines = [f"# FDD-1 release regression — {report['status']}", "",
             f"Baseline `{report['baseline_commit'][:7]}` · candidate `{report['candidate_commit'][:7]}` · {report['started_at']} → {report['finished_at']}",
             "", "| Stage | Component | Status | Detail |", "|---|---|---|---|"]
    for s in report["stages"]:
        detail = {k: v for k, v in s.items() if k not in ("name", "component", "status", "per_component", "failures", "fixed_since_baseline")}
        lines.append(f"| {s['name']} | {s['component']} | **{s['status']}** | `{json.dumps(detail, default=str)[:400]}` |")
    tests = next((s for s in report["stages"] if s["name"] == "full_test_suite"), None)
    if tests:
        lines += ["", "## Test suite by component", "", "| Component | Passed | Failed | Errors | Skipped |", "|---|---:|---:|---:|---:|"]
        for name, counts in tests["per_component"].items():
            lines.append(f"| {name} | {counts.get('passed', 0)} | {counts.get('failed', 0)} | {counts.get('error', 0)} | {counts.get('skipped', 0)} |")
        lines += ["", "## Failures", ""] + [f"- {f['status']}: `{f['test']}` (baseline: {f['baseline']})" for f in tests["failures"]] or ["- none"]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-junit", type=Path, default=REPORTS / "baseline" / "junit_baseline.xml")
    parser.add_argument("--baseline-commit", default="9759dc00a0ba3a390af37efcfcffff5589e837e9")
    parser.add_argument("--skip-live", action="store_true")
    parser.add_argument("--skip-model", action="store_true")
    parser.add_argument("--load-seconds", type=float, default=180)
    args = parser.parse_args(argv)
    REPORTS.mkdir(parents=True, exist_ok=True)
    started = now()
    stages = [stage_tests(args.baseline_junit, REPORTS)]
    stages.append(dict(name="model_regression", component="inference", status="NOT_VERIFIED", reason="skipped by flag")
                  if args.skip_model else stage_model(REPORTS))
    if args.skip_live:
        stages.append(dict(name="live_stack", component="system", status="NOT_VERIFIED", reason="skipped by --skip-live"))
    else:
        stages.extend(stage_live(REPORTS, args.load_seconds))
    stages.append(dict(name="physical_offline", component="system", status="NOT_VERIFIED",
                       reason="no physical network disconnection; offline enforced by loopback-only config, socket guards and import checks"))
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    report = dict(task="FDD-1", status=overall(stages), baseline_commit=args.baseline_commit, candidate_commit=commit,
                  started_at=started, finished_at=now(), python=platform.python_version(), interpreter=sys.executable,
                  platform=platform.platform(), stages=stages)
    (REPORTS / "release_regression.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    (REPORTS / "release_regression.md").write_text(markdown(report), encoding="utf-8")
    for s in stages:
        print(f"{s['status']:<17} {s['name']:<36} {s['component']}")
    print(f"OVERALL {report['status']} -> {REPORTS / 'release_regression.json'}")
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
