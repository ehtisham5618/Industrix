"""FDD-5 tests: readiness classification, report contract, safe output, results-table parsing and
dashboard/backend comparison, readiness waits and timeouts, offline guard, refusal to touch busy
ports, cleanup on interruption, and consistency between the docs, the CLI and the committed evidence."""
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from pydantic import ValidationError

from FDD_5_Dry_Run import rehearse as rh

ROOT = Path(__file__).resolve().parents[2]


def check(status, required=True):
    return rh.CheckResult(stage="A", name="x", status=status, required=required)


@pytest.mark.parametrize("statuses,expected", [
    ([], "INCOMPLETE"),
    (["PASS", "PASS"], "READY"),
    (["PASS", "FAIL"], "NOT READY"),
    (["PASS", "BLOCKED"], "NOT READY"),
    (["PASS", "NOT VERIFIED"], "NOT READY"),  # a skipped required check is never a pass
])
def test_readiness_classification(statuses, expected):
    assert rh.classify([check(s) for s in statuses]) == expected


def test_optional_checks_do_not_block_readiness():
    assert rh.classify([check("PASS"), check("NOT VERIFIED", required=False), check("FAIL", required=False)]) == "READY"


def test_report_contract_round_trips_and_rejects_unknown_status():
    report = rh.RehearsalReport(started_at="t", git_revision="abc", environment={"os": "x"}, checks=[check("PASS")])
    again = rh.RehearsalReport.model_validate_json(report.model_dump_json())
    assert again.checks[0].status == "PASS" and again.readiness == "INCOMPLETE"
    with pytest.raises(ValidationError):
        check("OK")


def test_report_paths_are_redacted():
    text = rh.redact(f"{rh.ROOT}/Backend/best.pt and {Path.home()}/x")
    assert str(rh.ROOT) not in text and str(Path.home()) not in text and "<repo>" in text


def test_safe_report_path_never_overwrites(tmp_path):
    first = rh.safe_report_path(tmp_path, "s1")
    first.write_text("{}", encoding="utf-8")
    with pytest.raises(rh.RehearsalError, match="refusing to overwrite"):
        rh.safe_report_path(tmp_path, "s1")
    assert first.read_text(encoding="utf-8") == "{}"


def test_results_table_parsing_and_backend_comparison():
    text = "Defect\n\n\t\n\nConfidence\n\n\n\nfire\n\n\t\n\n81.7%\n\n\nsmoke\n\t\n40.0%\n\ncolor issues\n\t\n32.5%"
    rows = rh.parse_results_table(text)
    assert rows == [("fire", "81.7%"), ("smoke", "40.0%"), ("color issues", "32.5%")]
    payload = {"detections": [{"class_name": "fire", "confidence": 0.8168}, {"class_name": "smoke", "confidence": 0.4},
                              {"class_name": "color issues", "confidence": 0.32549}]}
    assert rh.backend_rows(payload) == rows
    assert rh.backend_rows({"detections": [{"class_name": "fire", "confidence": 0.5}]}) != rows
    with pytest.raises(ValueError, match="unexpected results table"):
        rh.parse_results_table("Class\nScore\nfire")


def test_wait_until_success_timeout_and_exceptions():
    calls = iter([False, True])
    assert rh.wait_until(lambda: next(calls), 5, 0.01) is not None
    assert rh.wait_until(lambda: False, 0.05, 0.01) is None

    def boom():
        raise ConnectionError("not up yet")
    assert rh.wait_until(boom, 0.05, 0.01) is None  # an exception is "not ready", not a crash


def test_status_file_errors_mean_not_healthy(tmp_path, monkeypatch):
    bad = tmp_path / "status.json"
    bad.write_text("{truncated", encoding="utf-8")
    assert rh.read_status(bad) == {}
    monkeypatch.setattr(rh, "STATUS_FILE", bad)
    assert rh.all_healthy() is False and rh.service_pid("backend") is None
    services = [{"name": "backend", "state": "healthy", "owned": True, "pid": 7}, {"name": "dashboard", "state": "starting"}]
    bad.write_text(json.dumps({"running": True, "services": services}), encoding="utf-8")
    assert rh.all_healthy() is False and rh.service_pid("backend") == 7


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"model_loaded": true}' if self.path == "/health" else b"not json"
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def test_readiness_probe_against_real_local_server_and_dead_port():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        code, body, err = rh.smoke_test.request("GET", url + "/health", timeout=5)
        assert code == 200 and json.loads(body)["model_loaded"] is True
        code, body, _ = rh.smoke_test.request("GET", url + "/other", timeout=5)
        with pytest.raises(ValueError):  # a malformed response is detected by the JSON parse
            json.loads(body)
    finally:
        server.shutdown()
    code, _, err = rh.smoke_test.request("GET", f"http://127.0.0.1:{rh.free_port()}/health", timeout=2)
    assert code is None and err


def test_busy_ports_are_refused_without_touching_processes(tmp_path, monkeypatch):
    monkeypatch.setattr(rh, "port_busy", lambda port: True)
    started = []
    monkeypatch.setattr(rh.Rehearsal, "stage_a", lambda self: started.append("A") or True)
    rehearsal = rh.Rehearsal(tmp_path, "python", "s")
    assert rehearsal.execute(False, False, False) == 3 and started == []
    assert "refused" in rehearsal.report.notes[0]


def test_services_are_stopped_when_interrupted(tmp_path, monkeypatch):
    monkeypatch.setattr(rh, "port_busy", lambda port: False)
    monkeypatch.setattr(rh.Rehearsal, "stage_a", lambda self: True)
    monkeypatch.setattr(rh.ResourceSampler, "start", lambda self: self)

    def interrupted(self):
        raise KeyboardInterrupt
    stopped = []
    monkeypatch.setattr(rh.Rehearsal, "stage_b", interrupted)
    monkeypatch.setattr(rh.Rehearsal, "stop_services", lambda self, stage, label: stopped.append(label) or True)
    with pytest.raises(KeyboardInterrupt):
        rh.Rehearsal(tmp_path, "python", "s").execute(False, False, True)
    assert stopped == ["D12"]


def test_preflight_failure_starts_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(rh, "port_busy", lambda port: False)
    monkeypatch.setattr(rh.Rehearsal, "stage_a", lambda self: False)
    monkeypatch.setattr(rh.Rehearsal, "stage_b", lambda self: pytest.fail("must not start services"))
    assert rh.main(["--out-dir", str(tmp_path)]) == 2
    report = json.loads(next(tmp_path.glob("rehearsal_*.json")).read_text(encoding="utf-8"))
    assert report["readiness"] in ("NOT READY", "INCOMPLETE") and "nothing was started" in report["notes"][0]


def test_free_port_is_bindable():
    port = rh.free_port()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", port))


def test_offline_guard_and_no_cloud_clients():
    source = (ROOT / "FDD_5_Dry_Run" / "rehearse.py").read_text(encoding="utf-8")
    assert 'context.route("**/*", guard)' in source and "route.abort()" in source
    for banned in ("import requests", "openai", "boto3", "import modal", "pip install"):
        assert banned not in source
    config = json.loads((ROOT / "EAP_5_Watchdog" / "configs" / "watchdog.json").read_text(encoding="utf-8"))
    env = config["services"][0]["env"]
    assert env["YOLO_OFFLINE"] == "true" and env["YOLO_AUTOINSTALL"] == "false"


def test_only_watchdog_owned_backend_is_killed():
    source = (ROOT / "FDD_5_Dry_Run" / "rehearse.py").read_text(encoding="utf-8")
    assert source.count(".kill()") == 2 and 'if svc.get("name") == name and svc.get("owned")' in source


def test_documented_commands_exist():
    doc = (ROOT / "docs" / "demo" / "DEMO_DAY_DRY_RUN.md").read_text(encoding="utf-8")
    for flag in ("--preflight-only", "--skip-ui", "--skip-restart"):
        assert flag in doc and flag in (ROOT / "FDD_5_Dry_Run" / "rehearse.py").read_text(encoding="utf-8")
    for module in ("FDD_5_Dry_Run.rehearse", "FDD_3_Deployment_Handoff.validate_deployment",
                   "FDD_3_Deployment_Handoff.smoke_test", "EAP_5_Watchdog"):
        assert module in doc
        assert (ROOT / module.split(".")[0]).is_dir()


REPORTS = sorted((ROOT / "reports" / "fdd5" / "rehearsal").glob("rehearsal_*.json"))


@pytest.mark.skipif(not REPORTS, reason="no rehearsal evidence yet")
def test_latest_rehearsal_report_is_consistent():
    report = rh.RehearsalReport.model_validate_json(REPORTS[-1].read_text(encoding="utf-8"))
    assert report.readiness == rh.classify(report.checks)
    for c in report.checks:
        for path in c.evidence:
            assert (ROOT / path).is_file(), path
    text = REPORTS[-1].read_text(encoding="utf-8")
    assert str(ROOT) not in text and str(ROOT).replace("\\", "\\\\") not in text
