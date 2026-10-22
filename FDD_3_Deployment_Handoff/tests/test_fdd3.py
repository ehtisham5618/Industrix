"""FDD-3 tests: deployment validator, smoke test (against local stubs), and documentation that
must stay consistent with the real code (env vars, endpoints, scripts, paths)."""
import json
import re
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from FDD_3_Deployment_Handoff import smoke_test as smoke
from FDD_3_Deployment_Handoff import validate_deployment as vd

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs" / "deployment"
PACKAGE = ["PRODUCTION_RUNBOOK.md", "DEPLOYMENT_GUIDE.md", "TROUBLESHOOTING.md", "ROLLBACK_AND_RECOVERY.md",
           "DEPLOYMENT_HANDOFF.md"]
ALL_DOCS = "\n".join((DOCS / name).read_text(encoding="utf-8") for name in PACKAGE)
RUNTIME_SOURCES = ["Backend", "Frontend", "SED_1_Multi_Camera/scripts", "SED_2_Alert_Escalation/scripts", "CME_OPT3_ByteTrack",
                   "Confidence_Calibration/scripts", "QCI_3_Severity_IoT", "QCI_4_Edge_Telemetry", "QCI_5_Incident_PDF",
                   "EAP_5_Watchdog"]


# ---- validator ---------------------------------------------------------------------------
def test_missing_and_mismatched_model_fail_clearly(tmp_path):
    missing = vd.check_model(tmp_path / "best.pt")
    assert missing.status == "FAIL" and "never downloaded" in missing.detail
    wrong = tmp_path / "best.pt"
    wrong.write_bytes(b"not the model")
    assert vd.check_model(wrong).status == "FAIL" and "SHA256" in vd.check_model(wrong).detail


def test_import_failures_are_reported_not_raised():
    checks = vd.check_imports(("definitely_not_a_module_xyz",), required=True)
    assert checks[0].status == "FAIL" and "ModuleNotFoundError" in checks[0].detail
    assert vd.check_imports(("definitely_not_a_module_xyz",), required=False)[0].status == "WARN"


def test_port_check_detects_listener():
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    try:
        assert vd.port_in_use(port)
    finally:
        server.close()
    assert not vd.port_in_use(port)


def test_unwritable_directory_is_a_failure(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    result = vd.check_writable([blocker / "sub"])  # a file cannot contain a directory
    assert result[0].status == "FAIL"


def test_validator_cli_exit_codes_and_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(vd, "run_checks", lambda expect: [vd.Check("a", "PASS", "ok"), vd.Check("b", "WARN", "w", False)])
    assert vd.main(["--json", str(tmp_path / "v.json")]) == 0
    assert json.loads((tmp_path / "v.json").read_text())["result"] == "PASS"
    monkeypatch.setattr(vd, "run_checks", lambda expect: [vd.Check("model_artifact", "FAIL", "missing")])
    assert vd.main([]) == 1 and "RESULT: FAIL" in capsys.readouterr().out


def test_validator_never_prints_secret_values(monkeypatch, capsys):
    monkeypatch.setenv("QCI3_SIREN_URL", "http://user:supersecret@127.0.0.1/siren")
    monkeypatch.setattr(vd, "run_checks", lambda expect: [vd.Check("python_version", "PASS", "ok")])
    vd.main([])
    assert "supersecret" not in capsys.readouterr().out


# ---- smoke test against a local stub -----------------------------------------------------------
GOOD = {"filename": "f.png", "detections": [{"class_id": 8, "class_name": "fire", "confidence": 0.9,
                                             "coordinates": {"x1": 1, "y1": 1, "x2": 10, "y2": 10}}]}


def stub_server(mode="ok", delay=0.0):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            time.sleep(delay)
            if self.path == "/health":
                self._send(200, {"model_loaded": mode != "no_model", "classes": 12})
            elif self.path == "/_stcore/health":
                self._send(200, b"ok", "text/plain")
            else:
                self._send(200, [])

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if b"not an image" in body:
                self._send(400 if mode != "accepts_garbage" else 200, {"detail": "Uploaded file is not a readable image."})
            elif mode == "bad_class":
                self._send(200, {"filename": "f", "detections": [dict(GOOD["detections"][0], class_name="chemical leak")]})
            else:
                self._send(200, GOOD)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


@pytest.mark.parametrize("mode,failing", [("ok", set()), ("no_model", {"backend_health"}),
                                          ("bad_class", {"predict_valid_image"}),
                                          ("accepts_garbage", {"predict_rejects_corrupt_upload"})])
def test_smoke_checks_detect_each_failure(mode, failing):
    server, url = stub_server(mode)
    try:
        results = smoke.run(url, url, timeout=5)
    finally:
        server.shutdown()
        server.server_close()
    assert {r["check"] for r in results if r["status"] == "FAIL"} == failing
    assert len(results) == 6


def test_smoke_handles_unreachable_and_timeouts_and_refuses_remote():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        closed = s.getsockname()[1]
    results = smoke.run(f"http://127.0.0.1:{closed}", None, timeout=5)
    assert all(r["status"] == "FAIL" for r in results) and "Error" in results[0]["detail"]
    server, url = stub_server(delay=2)
    try:
        started = time.monotonic()
        results = smoke.run(url, None, timeout=0.5)
        assert results[0]["status"] == "FAIL" and time.monotonic() - started < 30
    finally:
        server.shutdown()
        server.server_close()
    assert smoke.main(["--backend", "http://example.com:8000"]) == 3


def test_smoke_contract_validation():
    assert smoke.validate_predict(GOOD) == ""
    bad_conf = {"detections": [dict(GOOD["detections"][0], confidence=1.5)]}
    bad_box = {"detections": [dict(GOOD["detections"][0], coordinates={"x1": 5, "y1": 5, "x2": 1, "y2": 9})]}
    assert "confidence" in smoke.validate_predict(bad_conf) and "coordinates" in smoke.validate_predict(bad_box)
    assert smoke.validate_predict({}) == "missing detections list"


# ---- documentation consistency with code -----------------------------------------------------------
def code_env_vars() -> set[str]:
    pattern = re.compile(r"os\.(?:getenv|environ\.get)\(\s*['\"]([A-Z][A-Z0-9_]+)['\"]|os\.environ\[['\"]([A-Z][A-Z0-9_]+)['\"]\]"
                         r"|['\"]([A-Z][A-Z0-9_]+)['\"]\s+in\s+os\.environ")
    names = set()
    for rel in RUNTIME_SOURCES:
        for path in (ROOT / rel).rglob("*.py"):
            if "tests" in path.parts or "runtime" in path.parts:
                continue
            for match in pattern.finditer(path.read_text(encoding="utf-8", errors="replace")):
                names.add(next(g for g in match.groups() if g))
    return names


def test_every_runtime_environment_variable_is_documented():
    guide = (DOCS / "DEPLOYMENT_GUIDE.md").read_text(encoding="utf-8")
    undocumented = sorted(n for n in code_env_vars() if f"`{n}`" not in guide)
    assert not undocumented, undocumented


def test_documented_variables_exist_in_code():
    guide = (DOCS / "DEPLOYMENT_GUIDE.md").read_text(encoding="utf-8")
    table = guide.split("## 5. Configuration reference", 1)[1].split("## 6.", 1)[0]
    documented = set(re.findall(r"^\| `([A-Z][A-Z0-9_]+)`", table, re.M))
    documented |= {"YOLO_AUTOINSTALL"}  # second name in a combined row
    assert documented and not (documented - code_env_vars() - {"YOLO_OFFLINE", "YOLO_AUTOINSTALL"})


def test_documented_endpoints_exist_in_the_api():
    pytest.importorskip("fastapi")
    try:
        import Backend.main as main
    except Exception as exc:  # heavy deps missing in a light environment
        pytest.skip(f"backend not importable here: {type(exc).__name__}")
    paths = set(main.api_app.openapi()["paths"])
    mentioned = set(re.findall(r"`(?:GET |POST )?(/(?:health|predict|system/status|incidents|cameras|alerts|edge|qci3|streams)[^`\s]*)`", ALL_DOCS))
    normalized = {re.sub(r"\{[^}]+\}", "{}", p) for p in paths}
    unknown = [m for m in mentioned if re.sub(r"\{[^}]+\}", "{}", m.rstrip("*").rstrip("/")) not in normalized
               and not m.endswith("*")]
    assert not unknown, unknown


def test_referenced_modules_scripts_and_paths_exist():
    modules = set(re.findall(r"-m ((?:EAP|FDD)_[A-Za-z0-9_]+(?:\.[a-z_]+)?)", ALL_DOCS))
    assert modules
    for module in modules:
        parts = module.split(".")
        candidate = ROOT.joinpath(*parts)
        assert candidate.with_suffix(".py").is_file() or (candidate / "__main__.py").is_file(), module
    for rel in ("EAP_5_Watchdog/scripts/setup_watchdog.ps1", "EAP_5_Watchdog/scripts/setup_watchdog.sh",
                "EAP_5_Watchdog/configs/watchdog.json", "Confidence_Calibration/configs/calibrated_thresholds.yaml",
                "docs/specifications/hazard_taxonomy.v1.json", "requirements.txt", "Frontend/requirements.txt", "Dockerfile"):
        assert rel in ALL_DOCS and (ROOT / rel).exists(), rel
    for link in re.findall(r"\]\(([^)#]+\.md)\)", ALL_DOCS):
        assert (DOCS / link).resolve().is_file(), link


def test_runbook_package_has_required_sections():
    runbook = (DOCS / "PRODUCTION_RUNBOOK.md").read_text(encoding="utf-8")
    for heading in ("System overview", "Start and stop", "Logs and records", "Monitoring", "mermaid"):
        assert heading in runbook, heading
    handoff = (DOCS / "DEPLOYMENT_HANDOFF.md").read_text(encoding="utf-8")
    for heading in ("Summary", "Operational reference", "Security and access", "Acceptance and known limitations", "quick-start"):
        assert heading in handoff, heading
    assert "NOT VERIFIED" in ALL_DOCS and "no authentication" in handoff
