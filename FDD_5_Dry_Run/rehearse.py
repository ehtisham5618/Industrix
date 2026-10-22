"""FDD-5 Demo Day dry-run rehearsal of the REAL IndustriX application.

python -m FDD_5_Dry_Run.rehearse [--preflight-only] [--skip-ui] [--skip-restart] [--out-dir reports/fdd5/rehearsal]

Stage A  environment readiness (FDD-3 validate_deployment + browser/recording prerequisites)
Stage B  startup through the EAP-5 watchdog, readiness wait, FDD-3 smoke test (backend + dashboard)
Stage C  demo workflow in the real dashboard (headless Edge): upload approved samples, Detect Defects,
         compare the dashboard results table with a direct /predict on the same file, incident panel
Stage D  failure recovery: corrupt/non-image/malformed uploads, dashboard pointed at a dead backend,
         missing model and missing config (isolated temp files), client timeout, recorder preflight,
         backend crash -> watchdog auto-restart, graceful stop -> restart

Every check is PASS, FAIL, BLOCKED or NOT VERIFIED. Exit codes: 0 READY (no required check failed or was
blocked), 1 NOT READY, 2 preflight failed (nothing was started), 3 ports busy (refuses to touch other processes).
Services started here are always stopped in a finally block. Reports are timestamped and never overwritten.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from FDD_3_Deployment_Handoff import smoke_test, validate_deployment
from FDD_4_Demo.record_demo import LOOPBACK, settle

ROOT = Path(__file__).resolve().parents[1]
BACKEND, DASHBOARD = "http://127.0.0.1:8000", "http://127.0.0.1:8501"
STATUS_FILE = ROOT / "EAP_5_Watchdog" / "runtime" / "status.json"
WATCHDOG_CONFIG = ROOT / "EAP_5_Watchdog" / "configs" / "watchdog.json"
SAMPLES = {"textile": ROOT / "tests" / "assets" / "ife_ui3_textile.png", "hazard": ROOT / "tests" / "assets" / "ife_ui3_fire.png"}
Status = Literal["PASS", "FAIL", "BLOCKED", "NOT VERIFIED"]


class CheckResult(BaseModel):
    stage: str
    name: str
    status: Status
    required: bool = True
    detail: str = ""
    seconds: Optional[float] = None
    evidence: list[str] = Field(default_factory=list)


class RehearsalReport(BaseModel):
    task: str = "FDD-5"
    started_at: str
    finished_at: Optional[str] = None
    git_revision: str
    environment: dict[str, str]
    checks: list[CheckResult] = Field(default_factory=list)
    resources: dict = Field(default_factory=dict)
    offline: dict = Field(default_factory=dict)
    readiness: Literal["READY", "NOT READY", "INCOMPLETE"] = "INCOMPLETE"
    notes: list[str] = Field(default_factory=list)


class RehearsalError(Exception):
    """A stage cannot continue; the message says what to do."""


def redact(text: str) -> str:
    """Keep reports free of personal paths: repository and home directories become placeholders."""
    for path, token in ((str(ROOT), "<repo>"), (str(Path.home()), "~")):
        text = text.replace(path, token).replace(path.replace("\\", "/"), token)
    return text


def classify(checks: list[CheckResult]) -> str:
    """READY only if every required check passed; a required FAIL/BLOCKED/NOT VERIFIED is NOT READY."""
    if not checks:
        return "INCOMPLETE"
    return "READY" if all(c.status == "PASS" for c in checks if c.required) else "NOT READY"


def safe_report_path(out_dir: Path, stamp: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"rehearsal_{stamp}.json"
    if target.exists():
        raise RehearsalError(f"refusing to overwrite {target}")
    return target


def port_busy(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def run(cmd: list[str], timeout: float, env: Optional[dict] = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout, env=env)


def git_revision() -> str:
    try:
        out = run(["git", "rev-parse", "--short", "HEAD"], 15)
        dirty = run(["git", "status", "--porcelain", "--untracked-files=no"], 15).stdout.strip()
        return out.stdout.strip() + ("+uncommitted" if dirty else "") if out.returncode == 0 else "unknown"
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"


def read_status(path: Optional[Path] = None) -> dict:
    try:
        return json.loads((path or STATUS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def wait_until(predicate: Callable[[], bool], timeout: float, interval: float = 1.0) -> Optional[float]:
    """Seconds until predicate() is true, or None on timeout. Exceptions count as 'not yet'."""
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        try:
            if predicate():
                return round(time.monotonic() - started, 1)
        except Exception:
            pass
        time.sleep(interval)
    return None


def all_healthy() -> bool:
    status = read_status()
    return bool(status.get("running")) and all(s.get("state") == "healthy" for s in status.get("services", []))


def service_pid(name: str) -> Optional[int]:
    for svc in read_status().get("services", []):
        if svc.get("name") == name and svc.get("owned"):
            return svc.get("pid")
    return None


def parse_results_table(text: str) -> list[tuple[str, str]]:
    """Dashboard 'Defect | Confidence' table text -> [(class, '95.0%'), ...]."""
    cells = [line.strip() for line in text.splitlines() if line.strip()]
    if cells[:2] != ["Defect", "Confidence"] or len(cells) % 2:
        raise ValueError(f"unexpected results table: {cells[:6]}")
    return list(zip(cells[2::2], cells[3::2]))


def backend_rows(payload: dict) -> list[tuple[str, str]]:
    """The same rows the dashboard renders from a /predict payload (class name, rounded percent)."""
    return [(d.get("class_name", str(d.get("class_id", "?"))), f"{round(float(d.get('confidence', 0.0)) * 100, 1)}%")
            for d in payload.get("detections", [])]


class ResourceSampler:
    """Bounded background sampling of the backend RSS and system CPU (observations, not a gate)."""

    def __init__(self, interval: float = 2.0, maxlen: int = 2000):
        self.samples: deque = deque(maxlen=maxlen)
        self.remote_endpoints: set[str] = set()
        self.interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def _loop(self) -> None:
        import psutil
        started = time.monotonic()
        while not self._stop.wait(self.interval):
            pid = service_pid("backend")
            try:  # on Windows the owned PID is the venv launcher; the interpreter is its child, so measure the tree
                root = psutil.Process(pid) if pid else None
                tree = [root, *root.children(recursive=True)] if root else []
                rss = sum(proc.memory_info().rss for proc in tree) / 2**20 if tree else None
                for proc in tree:  # any non-loopback socket of the backend would contradict the offline claim
                    for conn in proc.net_connections(kind="inet"):
                        if conn.raddr and conn.raddr.ip not in LOOPBACK:
                            self.remote_endpoints.add(f"{conn.raddr.ip}:{conn.raddr.port}")
            except (psutil.Error, OSError):
                rss = None
            self.samples.append(dict(t=round(time.monotonic() - started, 1), backend_pid=pid,
                                     backend_rss_mib=round(rss, 1) if rss else None, cpu_system=psutil.cpu_percent()))

    def start(self) -> "ResourceSampler":
        self._thread.start()
        return self

    def stop(self) -> dict:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=10)
        rss = [s["backend_rss_mib"] for s in self.samples if s["backend_rss_mib"]]
        cpu = [s["cpu_system"] for s in self.samples]
        return dict(method=f"psutil every {self.interval:.0f} s: RSS summed over the watchdog-owned backend process tree; system CPU",
                    samples=len(self.samples), duration_s=self.samples[-1]["t"] if self.samples else 0,
                    backend_rss_mib=dict(first=rss[0], last=rss[-1], min=min(rss), max=max(rss)) if rss else None,
                    cpu_system_percent=dict(mean=round(sum(cpu) / len(cpu), 1), max=max(cpu)) if cpu else None,
                    memory_drift_5pct="NOT VERIFIED: a rehearsal of minutes with a backend restart is not a drift "
                                      "measurement (see EAP-4 for the long-run profile)",
                    series=list(self.samples))


class Rehearsal:
    def __init__(self, out_dir: Path, python: str, stamp: str):
        self.out_dir, self.python, self.stamp = out_dir, python, stamp
        self.evidence = out_dir / f"evidence_{stamp}"
        self.report = RehearsalReport(started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                      git_revision=git_revision(), environment=dict(
                                          os=platform.platform(), python=platform.python_version(),
                                          cpu=platform.processor() or platform.machine(), cpu_count=str(os.cpu_count())))
        self.blocked_requests: list[str] = []

    def add(self, stage: str, name: str, ok: Optional[bool], detail: str, required: bool = True,
            seconds: Optional[float] = None, evidence: Optional[list[str]] = None, status: Optional[Status] = None) -> CheckResult:
        result = CheckResult(stage=stage, name=name, required=required, detail=redact(detail)[:600], seconds=seconds,
                             evidence=evidence or [], status=status or ("PASS" if ok else "FAIL"))
        self.report.checks.append(result)
        print(f"[{stage}] {result.status:<12} {name:<40} {result.detail[:150]}", flush=True)
        return result

    def shot(self, page, name: str) -> str:
        self.evidence.mkdir(parents=True, exist_ok=True)
        path = self.evidence / f"{name}.png"
        page.screenshot(path=str(path))
        return path.relative_to(ROOT).as_posix()

    # Stage A ---------------------------------------------------------------------------------------
    def stage_a(self) -> bool:
        for c in validate_deployment.run_checks(expect_ports_free=True):
            status = {"PASS": "PASS", "FAIL": "FAIL"}.get(c.status, "NOT VERIFIED")
            self.add("A", c.name, None, c.detail, required=c.required, status=status)
        try:
            import playwright  # noqa: F401  # browser automation for the UI stage and recording
            self.add("A", "import:playwright", True, "available (UI rehearsal and FDD-4 recording)")
        except ImportError as exc:
            self.add("A", "import:playwright", False, f"{exc}: UI stage will be BLOCKED")
        edge = shutil.which("msedge") or next((p for p in (Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft/Edge/Application/msedge.exe",
                                                           Path(os.environ.get("ProgramFiles", "")) / "Microsoft/Edge/Application/msedge.exe")
                                               if p.is_file()), None)
        self.add("A", "browser:msedge", bool(edge), "Microsoft Edge found" if edge else "Microsoft Edge not found")
        for name, path in SAMPLES.items():
            self.add("A", f"sample:{name}", path.is_file(), f"{path.relative_to(ROOT).as_posix()}"
                     + (f" {path.stat().st_size:,} bytes" if path.is_file() else " missing"))
        tools = {t: shutil.which(t) for t in ("ffmpeg", "ffprobe")}
        self.add("A", "recording:ffmpeg", all(tools.values()), f"ffmpeg/ffprobe {'on PATH' if all(tools.values()) else 'missing'} "
                 "(needed only to record; the live demo does not use it)", required=False)
        return all(c.status == "PASS" for c in self.report.checks if c.stage == "A" and c.required)

    # Stage B ---------------------------------------------------------------------------------------
    def start_services(self, stage: str, label: str) -> bool:
        started = time.monotonic()
        result = run([self.python, "-m", "EAP_5_Watchdog", "start"], 120)
        if result.returncode:
            self.add(stage, f"{label}:watchdog_start", False, f"exit {result.returncode}: {result.stdout.strip()[-300:]}")
            return False
        ready = wait_until(all_healthy, 240, 2)
        self.add(stage, f"{label}:services_healthy", ready is not None,
                 f"backend /health model_loaded and dashboard /_stcore/health ok after {ready} s" if ready is not None
                 else "not healthy within 240 s: see EAP_5_Watchdog/runtime/logs/", seconds=round(time.monotonic() - started, 1))
        return ready is not None

    def stop_services(self, stage: str, label: str) -> bool:
        started = time.monotonic()
        result = run([self.python, "-m", "EAP_5_Watchdog", "stop", "--timeout", "90"], 150)
        freed = wait_until(lambda: not port_busy(8000) and not port_busy(8501), 30, 1)
        self.add(stage, f"{label}:graceful_stop", result.returncode == 0 and freed is not None,
                 f"watchdog stop exit {result.returncode}; ports 8000/8501 {'free' if freed is not None else 'STILL IN USE'}",
                 seconds=round(time.monotonic() - started, 1))
        return result.returncode == 0

    def stage_b(self) -> bool:
        if not self.start_services("B", "startup"):
            return False
        for r in smoke_test.run(BACKEND, DASHBOARD):
            self.add("B", f"smoke:{r['check']}", r["status"] == "PASS", r["detail"])
        return True

    # Stage C ---------------------------------------------------------------------------------------
    def predict(self, path: Path, timeout: float = 60) -> tuple[Optional[int], dict, str, float]:
        started = time.monotonic()
        code, body, err = smoke_test.request("POST", BACKEND + "/predict", *smoke_test.multipart(path.name, path.read_bytes()), timeout=timeout)
        payload = json.loads(body) if code == 200 else {}
        return code, payload, err, round(time.monotonic() - started, 2)

    def open_dashboard(self, page) -> None:
        page.goto(DASHBOARD, wait_until="domcontentloaded")
        page.get_by_role("button", name="Start three feeds").wait_for(timeout=60000)
        settle(page, 1000)

    def ui_inference(self, page, path: Path) -> tuple[list[tuple[str, str]], float]:
        self.open_dashboard(page)
        page.get_by_role("tab", name="Image Inference").click()
        page.get_by_text("Upload an image (JPG, JPEG, PNG)").first.wait_for(timeout=60000)
        page.locator("input[type=file]").first.set_input_files(str(path), timeout=60000)
        page.get_by_role("button", name="Detect Defects").wait_for(timeout=60000)
        clicked = time.monotonic()
        page.get_by_role("button", name="Detect Defects").click()
        page.get_by_text("Detection Results").wait_for(timeout=90000)
        seconds = round(time.monotonic() - clicked, 2)
        table = page.locator("table").last
        table.wait_for(timeout=30000)
        return parse_results_table(table.inner_text()), seconds

    def stage_c_and_ui_failures(self) -> None:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True,
                                        args=["--disable-background-networking", "--disable-component-update"])
            context = browser.new_context(viewport=dict(width=1600, height=1000))

            def guard(route):  # same offline guard as the FDD-4 recorder
                url = route.request.url
                if url.startswith(("file:", "data:", "blob:")) or urlparse(url).hostname in LOOPBACK:
                    route.continue_()
                else:
                    self.blocked_requests.append(url[:200])
                    route.abort()
            context.route("**/*", guard)
            page = context.new_page()
            try:
                self.open_dashboard(page)
                self.add("C", "C2:dashboard_opens", True, "Industrial Vision Console rendered with live monitor controls",
                         evidence=[self.shot(page, "c2_dashboard")])
                for step, (name, path) in enumerate(SAMPLES.items(), 3):
                    code, payload, err, api_s = self.predict(path)
                    api_rows = backend_rows(payload)
                    try:
                        ui_rows, ui_s = self.ui_inference(page, path)
                        page.get_by_text("Annotated result").first.scroll_into_view_if_needed()
                        shots = [self.shot(page, f"c{step}_{name}_annotated")]
                        page.locator("table").last.scroll_into_view_if_needed()
                        shots.append(self.shot(page, f"c{step}_{name}_table"))
                    except Exception as exc:
                        self.add("C", f"C{step}:{name}_inference", False, f"{type(exc).__name__}: {str(exc).splitlines()[0][:200]}",
                                 evidence=[self.shot(page, f"c{step}_{name}_failure")])
                        continue
                    self.add("C", f"C{step}:{name}_inference", code == 200 and bool(ui_rows),
                             f"dashboard {ui_rows} in {ui_s} s click-to-results (UI-observed); direct /predict HTTP {code} "
                             f"{err} in {api_s} s", seconds=ui_s, evidence=shots)
                    self.add("C", f"C{step}:{name}_dashboard_matches_backend", ui_rows == api_rows,
                             f"dashboard {ui_rows} vs backend {api_rows}")
                self.open_dashboard(page)
                anchor = page.get_by_text("Incident History").first
                anchor.wait_for(timeout=60000)
                settle(page)
                anchor.scroll_into_view_if_needed()
                code, body, err = smoke_test.request("GET", BACKEND + "/incidents")
                listing = json.loads(body) if code == 200 else {}
                self.add("C", "C5:incident_history_panel", code == 200,
                         f"panel rendered; /incidents HTTP {code} {err}; {len(listing.get('incidents', []))} hazard and "
                         f"{len(listing.get('quality_incidents', []))} quality incidents in the local store; "
                         f"logging_failures={listing.get('logging_failures')}", evidence=[self.shot(page, "c5_incident_history")])
                self.ui_dead_backend(page)
            finally:
                context.close()
                browser.close()
        self.add("C", "offline:browser_requests", not self.blocked_requests,
                 f"{len(self.blocked_requests)} non-loopback browser requests blocked: {self.blocked_requests[:3]}")

    def ui_dead_backend(self, page) -> None:
        """D: dashboard pointed at a backend that is not running must show the documented error, not crash."""
        dead = f"http://127.0.0.1:{free_port()}"
        self.open_dashboard(page)
        url_box = page.get_by_label("FastAPI Backend URL")
        url_box.fill(dead)
        url_box.press("Enter")
        settle(page, 1500)
        page.get_by_role("tab", name="Image Inference").click()
        page.get_by_text("Upload an image (JPG, JPEG, PNG)").first.wait_for(timeout=60000)
        page.locator("input[type=file]").first.set_input_files(str(SAMPLES["textile"]), timeout=60000)
        page.get_by_role("button", name="Detect Defects").click()
        message = page.get_by_text("FastAPI backend is unavailable")
        try:
            message.first.wait_for(timeout=30000)
            shown = True
        except Exception:
            shown = False
        evidence = [self.shot(page, "d_dashboard_backend_unavailable")]
        self.open_dashboard(page)  # a fresh session restores the default backend URL
        recovered = page.get_by_label("FastAPI Backend URL").input_value() == BACKEND
        self.add("D", "D1:dashboard_backend_unreachable", shown and recovered,
                 f"error {'shown' if shown else 'NOT shown'} for {dead}; app kept running; reload restored {BACKEND}: {recovered}",
                 evidence=evidence)

    # Stage D (API, configuration and process scenarios) ----------------------------------------------
    def stage_d_api(self) -> None:
        cases = [("D2:corrupt_png_rejected", "corrupt.png", b"\x89PNG\r\n\x1a\n truncated", 400),
                 ("D3:text_file_rejected", "notes.png", b"this is not an image", 400)]
        for name, filename, data, expected in cases:
            code, body, err = smoke_test.request("POST", BACKEND + "/predict", *smoke_test.multipart(filename, data))
            self.add("D", name, code == expected, f"HTTP {code} {body[:120]!r} {err}")
        code, body, err = smoke_test.request("POST", BACKEND + "/predict", b"", "multipart/form-data; boundary=x")
        self.add("D", "D4:malformed_request_rejected", code in (400, 422), f"empty multipart body -> HTTP {code} {err}")
        code, _, err = smoke_test.request("POST", BACKEND + "/predict", *smoke_test.multipart("f.png", SAMPLES["hazard"].read_bytes()), timeout=0.001)
        self.add("D", "D5:client_timeout_reported", code is None and bool(err), f"1 ms client timeout -> {err or code} (no crash)")
        code, body, _ = smoke_test.request("GET", BACKEND + "/health")
        self.add("D", "D5b:backend_healthy_after_bad_requests", code == 200 and json.loads(body).get("model_loaded") is True, f"HTTP {code}")

    def stage_d_offline_config(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fdd5-", dir=ROOT / "FDD_5_Dry_Run" / "runtime") as tmp:
            tmp_dir = Path(tmp)
            check = validate_deployment.check_model(tmp_dir / "missing_best.pt")
            self.add("D", "D6:missing_model_detected", check.status == "FAIL" and "missing" in check.detail, check.detail)
            config = json.loads(WATCHDOG_CONFIG.read_text(encoding="utf-8"))
            config["services"][0]["env"]["INDUSTRIX_MODEL_PATH"] = str(tmp_dir / "missing_best.pt")
            bad_model = tmp_dir / "missing_model.json"
            bad_model.write_text(json.dumps(config), encoding="utf-8")
            result = run([self.python, "-m", "EAP_5_Watchdog", "validate", "--config", str(bad_model)], 60)
            self.add("D", "D7:backend_start_refused_without_model", result.returncode != 0,
                     f"watchdog validate exit {result.returncode}: {(result.stdout + result.stderr).strip()[-250:]}")
            config = json.loads(WATCHDOG_CONFIG.read_text(encoding="utf-8"))
            del config["services"]
            no_services = tmp_dir / "missing_services.json"
            no_services.write_text(json.dumps(config), encoding="utf-8")
            result = run([self.python, "-m", "EAP_5_Watchdog", "validate", "--config", str(no_services)], 60)
            self.add("D", "D8:missing_config_value_reported", result.returncode != 0,
                     f"watchdog validate exit {result.returncode}: {(result.stdout + result.stderr).strip()[-250:]}")
        from FDD_4_Demo import record_demo
        try:
            record_demo.preflight(record_demo.load_manifest(), which=lambda name: None)
            self.add("D", "D9:recording_prerequisite_missing", False, "preflight accepted a missing ffmpeg")
        except record_demo.DemoError as exc:
            self.add("D", "D9:recording_prerequisite_missing", True, f"recorder preflight refuses: {exc}")
        dead = f"http://127.0.0.1:{free_port()}"
        code, _, err = smoke_test.request("GET", dead + "/health", timeout=2)
        self.add("D", "D10:readiness_probe_unreachable_backend", code is None and bool(err), f"{dead}/health -> {err}")

    def stage_d_crash_restart(self) -> None:
        """Backend killed (watchdog-owned PID only) -> the watchdog must restart it and /predict must work again."""
        import psutil
        pid = service_pid("backend")
        if not pid:
            self.add("D", "D11:backend_crash_auto_restart", None, "no watchdog-owned backend PID", status="BLOCKED")
            return
        started = time.monotonic()
        proc = psutil.Process(pid)
        for child in proc.children(recursive=True):
            child.kill()
        proc.kill()
        recovered = wait_until(lambda: service_pid("backend") not in (None, pid) and all_healthy(), 300, 2)
        code, payload, err, _ = self.predict(SAMPLES["hazard"]) if recovered is not None else (None, {}, "not recovered", 0)
        status = read_status()
        backend = next((s for s in status.get("services", []) if s.get("name") == "backend"), {})
        self.add("D", "D11:backend_crash_auto_restart", recovered is not None and code == 200,
                 f"killed backend PID; watchdog restarted it (new PID) and services were healthy after {recovered} s; "
                 f"/predict HTTP {code} {len(payload.get('detections', []))} detections {err}; "
                 f"restart reason {backend.get('last_restart_reason')!r}",
                 seconds=round(time.monotonic() - started, 1))

    # Orchestration ---------------------------------------------------------------------------------
    def execute(self, preflight_only: bool, skip_ui: bool, skip_restart: bool) -> int:
        if not preflight_only and (port_busy(8000) or port_busy(8501)):
            self.report.notes.append("Ports 8000/8501 busy: refused to touch processes this rehearsal did not start.")
            return 3
        if not self.stage_a():
            self.report.notes.append("Stage A failed: nothing was started.")
            return 2
        if preflight_only:
            self.report.notes.append("--preflight-only: stages B-D not run.")
            return 0
        sampler = ResourceSampler().start()
        try:
            if self.stage_b():
                if skip_ui:
                    self.add("C", "C:dashboard_workflow", None, "--skip-ui given", status="NOT VERIFIED")
                else:
                    try:
                        self.stage_c_and_ui_failures()
                    except Exception as exc:  # report and continue with the API/recovery stages
                        self.add("C", "C:dashboard_workflow", False, f"{type(exc).__name__}: {str(exc).splitlines()[0][:250]}")
                self.stage_d_api()
                self.stage_d_offline_config()
                if skip_restart:
                    self.add("D", "D11:backend_crash_auto_restart", None, "--skip-restart given", status="NOT VERIFIED")
                else:
                    self.stage_d_crash_restart()
            else:
                for stage in ("C", "D"):
                    self.add(stage, f"{stage}:not_run", None, "startup failed", status="BLOCKED")
        finally:
            self.stop_services("D", "D12")
            self.report.resources = sampler.stop()
        if not skip_restart:
            try:
                if self.start_services("D", "D12:restart"):
                    smoke = smoke_test.run(BACKEND, DASHBOARD)
                    self.add("D", "D12:restart_smoke", all(r["status"] == "PASS" for r in smoke),
                             f"{sum(r['status'] == 'PASS' for r in smoke)}/{len(smoke)} smoke checks passed after a clean restart")
            finally:
                self.stop_services("D", "D12:final")
        self.report.offline = dict(
            browser_non_loopback_requests_blocked=len(self.blocked_requests),
            backend_non_loopback_connections=sorted(sampler.remote_endpoints),
            env="watchdog starts the backend with YOLO_OFFLINE=true, YOLO_AUTOINSTALL=false",
            physical_network_isolation="NOT VERIFIED: the network adapter was not disabled",
        )
        return 0

    def finish(self, report_path: Path) -> str:
        self.report.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.report.readiness = classify(self.report.checks)
        report_path.write_text(self.report.model_dump_json(indent=2), encoding="utf-8")
        return self.report.readiness


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out-dir", type=Path, default=ROOT / "reports" / "fdd5" / "rehearsal")
    parser.add_argument("--python", default=sys.executable, help="interpreter with the full IndustriX stack")
    parser.add_argument("--preflight-only", action="store_true", help="stage A only; starts nothing")
    parser.add_argument("--skip-ui", action="store_true", help="no browser stage (marked NOT VERIFIED)")
    parser.add_argument("--skip-restart", action="store_true", help="no crash/restart scenarios (marked NOT VERIFIED)")
    args = parser.parse_args(argv)
    os.environ.setdefault("YOLO_OFFLINE", "true")
    (ROOT / "FDD_5_Dry_Run" / "runtime").mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = args.out_dir.resolve()
    try:
        report_path = safe_report_path(out_dir, stamp)
    except RehearsalError as exc:
        print(f"REHEARSAL ERROR: {exc}")
        return 1
    rehearsal = Rehearsal(out_dir, args.python, stamp)
    try:
        code = rehearsal.execute(args.preflight_only, args.skip_ui, args.skip_restart)
    except KeyboardInterrupt:
        rehearsal.report.notes.append("interrupted by the operator; services were stopped")
        code = 1
    readiness = rehearsal.finish(report_path)
    if code in (2, 3):
        readiness = "NOT READY"
    print(f"REHEARSAL: {readiness} — report {redact(str(report_path))}")
    if code:
        return code
    return 0 if readiness == "READY" else 1


if __name__ == "__main__":
    sys.exit(main())
