"""EAP-5 watchdog tests: config, health, restart policy, supervisor state machine (fakes),
real-subprocess failure/recovery with a disposable service, locking, offline and setup scripts."""
import ast
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest
from pydantic import ValidationError

from EAP_5_Watchdog import __main__ as cli
from EAP_5_Watchdog.config import (ConfigError, HealthCheck, RestartPolicyConfig, ServiceConfig, WatchdogConfig,
                                   expand, load_config, redact_env, validate_runtime)
from EAP_5_Watchdog.contracts import HealthResult, ServiceState
from EAP_5_Watchdog.health import check, check_http
from EAP_5_Watchdog.policy import RestartPolicy
from EAP_5_Watchdog.process import InstanceLock, LockError
from EAP_5_Watchdog.supervisor import Watchdog

TASK = Path(__file__).resolve().parents[1]
ROOT = TASK.parent
DUMMY = Path(__file__).with_name("dummy_service.py")


# ---- helpers -------------------------------------------------------------------------
class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


class FakeProcess:
    """Stands in for ManagedProcess; records starts/stops without spawning anything."""
    instances = []

    def __init__(self, name, command, cwd, env, log_dir, max_log_bytes):
        self.name, self.command, self.env = name, command, env
        self.running, self.starts, self.stops, self.pid = False, 0, 0, None
        FakeProcess.instances.append(self)

    def start(self):
        self.running, self.starts = True, self.starts + 1
        self.pid = 40000 + len(FakeProcess.instances)
        return self.pid

    def alive(self):
        return self.running

    def exit_code(self):
        return None if self.running else 1

    def log_oversized(self):
        return False

    def stop(self, timeout):
        self.stops += 1
        mode = "graceful" if self.running else "already_exited"
        self.running = False
        return 0, mode


def service(name="svc", port=None, **overrides):
    data = dict(name=name, command=[sys.executable, "-c", "pass"], cwd=str(ROOT), port=port,
                health=dict(kind="http", url=f"http://127.0.0.1:{port or 9}/health"), interval_seconds=1,
                startup_grace_seconds=5, restart=dict(failure_threshold=3, cooldown_seconds=10, backoff_initial_seconds=10,
                                                      backoff_multiplier=2, backoff_max_seconds=40, max_restarts=3,
                                                      window_seconds=600, recovery_timeout_seconds=20))
    data.update(overrides)
    return data


CREATED = []


@pytest.fixture(autouse=True)
def close_watchdogs(tmp_path):  # depends on tmp_path so it closes files before cleanup
    yield
    while CREATED:
        CREATED.pop().close()


def make_watchdog(tmp_path, services, health, clock=None, ports=None):
    cfg = WatchdogConfig(runtime_dir=str(tmp_path / "rt"), tick_seconds=0.1, event_buffer=32,
                         services=[ServiceConfig.model_validate(s) for s in services])
    FakeProcess.instances = []
    clock = clock or Clock()
    wd = Watchdog(cfg, clock=clock, process_factory=FakeProcess, http_checker=lambda spec: health[spec.url](),
                  port_probe=lambda port: (ports or {}).get(port), console=False)
    CREATED.append(wd)
    return wd, clock


def ok():
    return HealthResult(ok=True, kind="http", status_code=200, detail="ok")


def bad():
    return HealthResult(ok=False, kind="http", status_code=503, detail="expected HTTP 200")


def run_ticks(wd, clock, seconds, step=1.0):
    for _ in range(int(seconds / step)):
        clock.advance(step)
        wd.tick()


def events(wd, name=None):
    return [e for e in wd.events if name is None or e.event == name]


# ---- configuration ---------------------------------------------------------------------
def test_shipped_config_is_valid_and_offline():
    cfg = load_config(TASK / "configs/watchdog.json")
    assert [s.name for s in cfg.services] == ["backend", "dashboard"]
    assert all(s.health.url.startswith("http://127.0.0.1:") for s in cfg.services)
    backend = cfg.services[0]
    assert backend.health.expect_json_true == "model_loaded" and backend.port == 8000
    assert cfg.services[1].health.url.endswith("/_stcore/health") and cfg.services[1].health.expect_body == "ok"


@pytest.mark.parametrize("bad_value", [dict(interval_seconds=0), dict(interval_seconds=-1), dict(startup_grace_seconds=-1),
                                       dict(restart=dict(failure_threshold=0)), dict(restart=dict(max_restarts=0)),
                                       dict(restart=dict(backoff_initial_seconds=50, backoff_max_seconds=10)),
                                       dict(restart=dict(window_seconds=0)), dict(command=[]), dict(name="Bad Name"),
                                       dict(health=dict(kind="http", url="http://example.com/health")),
                                       dict(health=dict(kind="http")), dict(health=dict(kind="http", url="http://127.0.0.1:1/h", timeout_seconds=0)),
                                       dict(unknown=1)])
def test_invalid_service_settings_rejected(bad_value):
    with pytest.raises(ValidationError):
        ServiceConfig.model_validate(service(**bad_value))


def test_missing_malformed_and_duplicate_config(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "none.json")
    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    with pytest.raises(ConfigError, match="not valid JSON"):
        load_config(broken)
    with pytest.raises(ValidationError, match="unique"):
        WatchdogConfig(services=[ServiceConfig.model_validate(service("svc-a")), ServiceConfig.model_validate(service("svc-a"))])
    with pytest.raises(ValidationError, match="port"):
        WatchdogConfig(services=[ServiceConfig.model_validate(service("svc-a", port=7000)),
                                 ServiceConfig.model_validate(service("svc-b", port=7000))])
    assert cli.main(["validate", "--config", str(broken)]) == 2


def test_runtime_validation_reports_missing_executable_cwd_and_env(tmp_path):
    cfg = WatchdogConfig(services=[ServiceConfig.model_validate(service("svc-a", command=["definitely-not-a-binary-xyz"])),
                                   ServiceConfig.model_validate(service("svc-b", cwd=str(tmp_path / "missing"))),
                                   ServiceConfig.model_validate(service("svc-c", env={"X": "{env:EAP5_UNSET_VAR}"})),
                                   ServiceConfig.model_validate(service("svc-d", enabled=False, command=["nope-xyz"]))])
    problems = validate_runtime(cfg, environ={})
    assert any("[svc-a] executable not found" in p for p in problems)
    assert any("[svc-b] working directory does not exist" in p for p in problems)
    assert any("EAP5_UNSET_VAR" in p for p in problems)
    assert not any("[svc-d]" in p for p in problems)  # disabled services are not validated or launched


def test_placeholders_are_limited_and_secrets_redacted():
    assert expand("{python}") == sys.executable and expand("{root}/x") == f"{ROOT}/x"
    assert expand("{env:A}", {"A": "1"}) == "1" and expand("{other}") == "{other}"
    assert redact_env({"API_TOKEN": "s3cret", "PORT": "1"}) == {"API_TOKEN": "<redacted>", "PORT": "<set>"}


def test_model_artifact_validation_without_download(tmp_path):
    cfg_ok = load_config(TASK / "configs/watchdog.json")
    if (ROOT / "Backend/best.pt").is_file():
        assert cli.model_artifact_problems(cfg_ok) == []
    data = json.loads((TASK / "configs/watchdog.json").read_text())
    data["services"][0]["env"]["INDUSTRIX_MODEL_PATH"] = str(tmp_path / "missing.pt")
    missing = WatchdogConfig.model_validate(data)
    assert "local model file missing" in cli.model_artifact_problems(missing)[0]


# ---- health checks (local stub server) ---------------------------------------------------
@pytest.fixture
def stub(tmp_path):
    control = tmp_path / "ctl"
    control.mkdir()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen([sys.executable, str(DUMMY), str(port), str(control)], stdout=subprocess.DEVNULL)
    spec = HealthCheck(url=f"http://127.0.0.1:{port}/health", expect_json_true="model_loaded", timeout_seconds=2)
    deadline = time.time() + 10
    while time.time() < deadline and not check_http(spec).ok:
        time.sleep(0.1)
    yield spec, control, port
    proc.kill()
    proc.wait()


def test_http_health_ok_failure_and_malformed(stub):
    spec, control, port = stub
    assert check_http(spec).ok
    (control / "unhealthy").write_text("1")
    result = check_http(spec)
    assert not result.ok and result.status_code == 503
    (control / "unhealthy").unlink()
    assert not check_http(spec.model_copy(update=dict(expect_body="nope"))).ok
    assert not check_http(spec.model_copy(update=dict(expect_json_true="missing_field"))).ok
    assert not check_http(spec.model_copy(update=dict(expect_status=204))).ok
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        closed = s.getsockname()[1]
    refused = check_http(HealthCheck(url=f"http://127.0.0.1:{closed}/health", timeout_seconds=3))
    assert not refused.ok and refused.detail


def test_health_timeout_is_bounded():
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)  # accepts the TCP connection but never answers
    try:
        started = time.monotonic()
        result = check_http(HealthCheck(url=f"http://127.0.0.1:{server.getsockname()[1]}/health", timeout_seconds=0.5))
        assert not result.ok and "timeout" in result.detail and time.monotonic() - started < 3
    finally:
        server.close()


def test_dead_process_is_unhealthy_without_probing():
    called = []
    result = check(HealthCheck(url="http://127.0.0.1:1/h"), False, lambda spec: called.append(1))
    assert not result.ok and result.kind == "process" and not called
    assert check(HealthCheck(kind="process"), True).ok


# ---- restart policy ------------------------------------------------------------------------
def test_policy_threshold_cooldown_backoff_cap_and_budget():
    p = RestartPolicy(RestartPolicyConfig(failure_threshold=3, cooldown_seconds=5, backoff_initial_seconds=10,
                                          backoff_multiplier=2, backoff_max_seconds=25, max_restarts=3, window_seconds=100))
    assert not p.threshold_reached(2) and p.threshold_reached(3)
    assert p.decide(0).action == "restart"
    p.record_restart(0)
    assert p.backoff() == 10 and p.decide(9).action == "wait" and p.decide(10).action == "restart"
    p.record_restart(10)
    assert p.backoff() == 20 and p.decide(29).action == "wait" and p.decide(30).action == "restart"
    p.record_restart(30)
    assert p.backoff() == 25  # capped
    blocked = p.decide(60)
    assert blocked.action == "circuit_open" and "budget exhausted" in blocked.reason
    assert p.decide(101).action == "restart"  # rolling window freed capacity
    p.record_stable()
    assert p.backoff() == 0
    assert len(p.restarts) <= 3  # bounded deque


# ---- supervisor state machine (fakes) --------------------------------------------------------
def test_healthy_service_is_not_restarted(tmp_path):
    wd, clock = make_watchdog(tmp_path, [service("svc-a", port=7101)], {"http://127.0.0.1:7101/health": ok})
    wd.start_all()
    run_ticks(wd, clock, 60)
    assert wd.services[0].state == ServiceState.HEALTHY and FakeProcess.instances[0].starts == 1
    assert not events(wd, "restart_initiated")


def test_startup_grace_and_transient_failures_do_not_restart(tmp_path):
    results = iter([bad(), bad(), bad(), ok()] + [bad(), ok()] * 10)
    wd, clock = make_watchdog(tmp_path, [service("svc-a", port=7102)], {"http://127.0.0.1:7102/health": lambda: next(results)})
    wd.start_all()
    run_ticks(wd, clock, 24)
    assert not events(wd, "restart_initiated")
    assert any(e.reason == "health restored without restart" for e in events(wd, "state_change"))


def test_threshold_restart_and_verified_recovery(tmp_path):
    state = {"ok": True}
    wd, clock = make_watchdog(tmp_path, [service("svc-a", port=7103)],
                              {"http://127.0.0.1:7103/health": lambda: ok() if state["ok"] else bad()})
    wd.start_all()
    run_ticks(wd, clock, 3)
    state["ok"] = False
    run_ticks(wd, clock, 2)
    assert wd.services[0].state == ServiceState.UNHEALTHY and not events(wd, "restart_initiated")
    run_ticks(wd, clock, 1)
    assert events(wd, "restart_initiated") and wd.services[0].state == ServiceState.RECOVERING
    run_ticks(wd, clock, 3)
    assert wd.services[0].state == ServiceState.RECOVERING  # not reported recovered while still failing
    state["ok"] = True
    run_ticks(wd, clock, 1)
    svc = wd.services[0]
    assert svc.state == ServiceState.HEALTHY and svc.last_recovery_outcome == "recovered"
    assert any(e.outcome == "recovered" for e in events(wd, "state_change"))


def test_failed_recovery_is_recorded_and_backoff_applies(tmp_path):
    wd, clock = make_watchdog(tmp_path, [service("svc-a", port=7104)], {"http://127.0.0.1:7104/health": bad})
    wd.start_all()
    run_ticks(wd, clock, 9)  # grace 5 s, then 3 failures -> restart
    assert len(events(wd, "restart_initiated")) == 1
    run_ticks(wd, clock, 21)  # recovery timeout 20 s
    assert events(wd, "recovery_failed") and wd.services[0].last_recovery_outcome == "failed"
    run_ticks(wd, clock, 120)
    restarts = events(wd, "restart_initiated")
    gaps = [b.monotonic_s - a.monotonic_s for a, b in zip(restarts, restarts[1:])]
    assert len(restarts) == 3 and all(g >= 10 for g in gaps)  # never faster than cooldown/backoff
    assert wd.services[0].state == ServiceState.DEGRADED  # budget (3) exhausted: no restart storm


def test_process_exit_triggers_restart_and_budget_opens_circuit_without_blocking_others(tmp_path):
    wd, clock = make_watchdog(tmp_path, [service("svc-a", port=7105), service("svc-b", port=7106)],
                              {"http://127.0.0.1:7105/health": ok, "http://127.0.0.1:7106/health": ok})
    wd.start_all()
    run_ticks(wd, clock, 3)
    crashing = wd.services[0]
    for _ in range(6):
        crashing.process.running = False  # crash
        run_ticks(wd, clock, 45)
    assert len(events(wd, "restart_initiated")) == 3  # max_restarts
    assert crashing.state == ServiceState.DEGRADED and events(wd, "circuit_open")
    assert wd.services[1].state == ServiceState.HEALTHY and wd.services[1].total_checks > 50
    gaps = [b.monotonic_s - a.monotonic_s for a, b in zip(events(wd, "restart_initiated"), events(wd, "restart_initiated")[1:])]
    assert all(g >= 10 for g in gaps)  # cooldown/backoff respected


def test_disabled_and_port_conflict_services_are_not_started(tmp_path):
    wd, clock = make_watchdog(tmp_path, [service("svc-a", port=7107, enabled=False), service("svc-b", port=7108)],
                              {"http://127.0.0.1:7107/health": ok, "http://127.0.0.1:7108/health": ok},
                              ports={7108: 4242})
    wd.start_all()
    run_ticks(wd, clock, 5)
    assert FakeProcess.instances == []
    assert wd.services[0].state == ServiceState.DISABLED
    assert wd.services[1].state == ServiceState.BLOCKED and "4242" in wd.services[1].detail


def test_missing_executable_is_a_config_error_not_a_crash(tmp_path):
    wd, clock = make_watchdog(tmp_path, [service("svc-a", port=7109, command=["no-such-binary-xyz"]), service("svc-b", port=7110)],
                              {"http://127.0.0.1:7109/health": ok, "http://127.0.0.1:7110/health": ok})
    wd.start_all()
    run_ticks(wd, clock, 3)
    assert wd.services[0].state == ServiceState.CONFIG_ERROR and events(wd, "start_failed")
    assert wd.services[1].state == ServiceState.HEALTHY


def test_events_bounded_status_fields_and_no_secret_values(tmp_path):
    wd, clock = make_watchdog(tmp_path, [service("svc-a", port=7111, env={"API_TOKEN": "super-secret-value"})],
                              {"http://127.0.0.1:7111/health": ok})
    wd.start_all()
    for _ in range(500):
        wd.emit("synthetic", wd.services[0])
    assert len(wd.events) == 32
    status = wd.status().model_dump()
    for key in ("state", "consecutive_failures", "last_success_at", "restarts_in_window", "last_restart_reason",
                "last_recovery_outcome"):
        assert key in status["services"][0]
    wd.write_status()
    log = (tmp_path / "rt/watchdog.jsonl").read_text()
    assert "super-secret-value" not in log and "<redacted>" in log
    assert "super-secret-value" not in (tmp_path / "rt/status.json").read_text()
    record = json.loads(log.splitlines()[0])
    assert {"ts", "monotonic_s", "event"} <= set(record)


def test_locked_status_file_does_not_stop_the_watchdog(tmp_path, monkeypatch):
    wd, clock = make_watchdog(tmp_path, [service("svc-a", port=7115)], {"http://127.0.0.1:7115/health": ok})
    wd.start_all()
    assert wd.write_status()
    from pathlib import Path as _Path

    def locked(self, target):
        raise PermissionError(5, "Access is denied")  # what Windows raises while a reader holds the file
    monkeypatch.setattr(_Path, "replace", locked)
    assert wd.write_status() is False  # no exception escapes
    assert events(wd, "status_write_failed")
    run_ticks(wd, clock, 3)
    assert wd.services[0].state == ServiceState.HEALTHY


def test_shutdown_stops_only_owned_processes(tmp_path):
    wd, clock = make_watchdog(tmp_path, [service("svc-a", port=7112), service("svc-b", port=7113, enabled=False)],
                              {"http://127.0.0.1:7112/health": ok, "http://127.0.0.1:7113/health": ok})
    wd.start_all()
    wd.shutdown("test")
    assert [p.stops for p in FakeProcess.instances] == [1]
    assert events(wd, "watchdog_stopped") and json.loads((tmp_path / "rt/status.json").read_text())["running"] is False


# ---- locking ---------------------------------------------------------------------------------
def test_instance_lock_blocks_duplicates_and_reclaims_stale(tmp_path):
    lock = InstanceLock(tmp_path / "w.lock")
    lock.acquire()
    with pytest.raises(LockError, match="another watchdog"):
        InstanceLock(tmp_path / "w.lock").acquire()
    lock.release()
    assert not (tmp_path / "w.lock").exists()
    (tmp_path / "w.lock").write_text(json.dumps(dict(pid=999999, create_time=1.0)))  # dead holder
    InstanceLock(tmp_path / "w.lock").acquire()
    assert json.loads((tmp_path / "w.lock").read_text())["pid"] == os.getpid()


def test_second_watchdog_run_refuses_without_touching_first(tmp_path):
    wd, _ = make_watchdog(tmp_path, [service("svc-a", port=7114)], {"http://127.0.0.1:7114/health": ok})
    wd.lock.acquire()
    try:
        other, _ = make_watchdog(tmp_path, [service("svc-a", port=7114)], {"http://127.0.0.1:7114/health": ok})
        assert other.run(max_seconds=1, install_signals=False) == 3
        assert FakeProcess.instances == [] and wd.lock.path.exists()
    finally:
        wd.lock.release()


# ---- real subprocess integration (disposable service) -----------------------------------------
def real_config(tmp_path, port, control):
    return WatchdogConfig.model_validate(dict(
        runtime_dir=str(tmp_path / "rt"), tick_seconds=0.2, event_buffer=64,
        services=[dict(name="dummy", command=["{python}", str(DUMMY), str(port), str(control)], cwd=str(tmp_path), port=port,
                       health=dict(kind="http", url=f"http://127.0.0.1:{port}/health", expect_json_true="model_loaded",
                                   timeout_seconds=2),
                       interval_seconds=0.5, startup_grace_seconds=10, stop_timeout_seconds=10,
                       restart=dict(failure_threshold=2, cooldown_seconds=1, backoff_initial_seconds=1, backoff_multiplier=2,
                                    backoff_max_seconds=4, max_restarts=2, window_seconds=600, recovery_timeout_seconds=15))]))


def wait_for(predicate, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.2)
    return False


def test_real_process_crash_unhealthy_restart_budget_and_cleanup(tmp_path, monkeypatch):
    original = socket.socket.connect
    outbound = []

    def guard(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            outbound.append(address)
            raise AssertionError(f"outbound connection attempted: {address}")
        return original(self, address)
    monkeypatch.setattr(socket.socket, "connect", guard)
    control = tmp_path / "ctl"
    control.mkdir()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    wd = Watchdog(real_config(tmp_path, port, control), console=False)
    CREATED.append(wd)
    import threading
    runner = threading.Thread(target=wd.run, kwargs=dict(max_seconds=120, install_signals=False))
    runner.start()
    svc = wd.services[0]
    try:
        assert wait_for(lambda: svc.state == ServiceState.HEALTHY), "dummy service never became healthy"
        first_pid = svc.process.pid
        (control / "crash").write_text("1")  # controlled crash
        assert wait_for(lambda: svc.state == ServiceState.HEALTHY and svc.policy.total == 1), "no verified recovery after crash"
        assert svc.process.pid != first_pid and not psutil.pid_exists(first_pid)
        (control / "unhealthy").write_text("1")  # alive but failing health
        assert wait_for(lambda: svc.policy.total == 2 and svc.state == ServiceState.RECOVERING)
        assert wait_for(lambda: svc.state == ServiceState.DEGRADED, timeout=40), "budget exhaustion did not open circuit"
        (control / "unhealthy").unlink()
        assert wait_for(lambda: svc.state == ServiceState.HEALTHY), "degraded service not observed recovering"
        child = svc.process.pid
    finally:
        wd.stop_event.set()
        runner.join(60)
    assert not runner.is_alive() and not psutil.pid_exists(child)
    assert not (tmp_path / "rt/watchdog.lock").exists() and outbound == []
    names = [e.event for e in wd.events]
    for expected in ("process_exited", "restart_initiated", "circuit_open", "process_stopped", "watchdog_stopped"):
        assert expected in names, expected
    assert any(e.event == "process_stopped" and e.outcome and e.outcome.startswith("graceful") for e in wd.events
               if e.reason and "shutdown" in e.reason)


# ---- offline + setup scripts --------------------------------------------------------------------
def test_watchdog_code_has_no_network_clients():
    banned = {"requests", "urllib3", "httpx", "aiohttp", "boto3", "mlflow", "modal"}
    for path in TASK.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        imported |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        assert not imported & banned, path.name


@pytest.mark.skipif(not shutil.which("sh"), reason="no POSIX sh available")
def test_posix_setup_script_syntax():
    assert subprocess.run(["sh", "-n", str(TASK / "scripts/setup_watchdog.sh")]).returncode == 0


@pytest.mark.skipif(os.name != "nt", reason="PowerShell setup script targets Windows")
def test_powershell_setup_script_parses_and_validates_idempotently():
    script = TASK / "scripts/setup_watchdog.ps1"
    parse = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "$e=$null;[void][System.Management.Automation.Language.Parser]::ParseFile("
                            f"'{script}',[ref]$null,[ref]$e);exit $e.Count"], capture_output=True, text=True)
    assert parse.returncode == 0, parse.stdout + parse.stderr
    for _ in range(2):  # repeated setup runs are safe
        run = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                              "-Action", "check", "-Python", sys.executable], capture_output=True, text=True, timeout=180)
        assert run.returncode == 0 and "CHECK OK" in run.stdout, run.stdout + run.stderr
