"""FDD-3 pre-deployment validation (read-only, offline, no model download).

python -m FDD_3_Deployment_Handoff.validate_deployment [--json out.json] [--expect-ports-free]

Exit codes: 0 all required checks pass, 1 a required check failed, 2 unexpected error.
Warnings (optional components) never fail the run. Secret-looking environment values are never printed.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import platform
import shutil
import socket
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
MODEL_SHA256 = "c4aba081f6357e23a7370a5f7cf98eff2c6faa0c4c20a2d4dcb8bcabdd490061"
REQUIRED_IMPORTS = ("fastapi", "uvicorn", "pydantic", "torch", "ultralytics", "cv2", "numpy", "psutil", "yaml", "reportlab", "pypdf")
OPTIONAL_IMPORTS = ("streamlit", "openvino")
PORTS = (8000, 8501)
MIN_FREE_BYTES = 5_000_000_000  # planning guidance from the hardware sizing guide (estimate, not an SLA)


@dataclass
class Check:
    name: str
    status: str  # PASS | FAIL | WARN
    detail: str
    required: bool = True


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def check_python() -> Check:
    ok = sys.version_info >= (3, 11)
    return Check("python_version", "PASS" if ok else "FAIL", f"{platform.python_version()} at {sys.executable} (need >= 3.11)")


def check_imports(modules: tuple[str, ...], required: bool) -> list[Check]:
    out = []
    for name in modules:
        try:
            module = importlib.import_module(name)
            out.append(Check(f"import:{name}", "PASS", str(getattr(module, "__version__", "ok")), required))
        except Exception as exc:  # report every import problem, do not stop at the first
            out.append(Check(f"import:{name}", "FAIL" if required else "WARN", f"{type(exc).__name__}: {exc}"[:200], required))
    return out


def check_model(path: Path, expected: str = MODEL_SHA256) -> Check:
    if not path.is_file():
        return Check("model_artifact", "FAIL", f"missing {path}: provision the verified best.pt (weights are not in Git, never downloaded)")
    actual = _sha256(path)
    if actual != expected:
        return Check("model_artifact", "FAIL", f"{path} SHA256 {actual} != approved {expected}")
    return Check("model_artifact", "PASS", f"{path.relative_to(ROOT) if path.is_relative_to(ROOT) else path} {path.stat().st_size:,} bytes, SHA256 verified")


def check_openvino_export() -> Check:
    xml = ROOT / "Backend/weights/openvino_int8/model.xml"
    present = xml.is_file() and xml.with_suffix(".bin").is_file()
    return Check("openvino_int8_export", "PASS" if present else "WARN",
                 "present (needed only for INFERENCE_ENGINE=openvino)" if present else "absent: only the PyTorch engine is available",
                 required=False)


def check_watchdog_config() -> Check:
    from EAP_5_Watchdog.__main__ import DEFAULT_CONFIG, model_artifact_problems
    from EAP_5_Watchdog.config import load_config, validate_runtime
    path = Path(os.getenv("INDUSTRIX_WATCHDOG_CONFIG", DEFAULT_CONFIG))
    try:
        config = load_config(path)
    except ValueError as exc:
        return Check("watchdog_config", "FAIL", f"{path}: {exc}"[:300])
    problems = validate_runtime(config) + model_artifact_problems(config)
    return Check("watchdog_config", "FAIL" if problems else "PASS", "; ".join(problems) if problems else
                 f"{path.name}: services {[s.name for s in config.services if s.enabled]}")


def check_taxonomy() -> Check:
    from FDD_2_Hardware_Taxonomy.taxonomy import cross_check, load_manifest
    try:
        problems = cross_check(load_manifest())
    except ValueError as exc:
        return Check("taxonomy_consistency", "FAIL", str(exc)[:300])
    return Check("taxonomy_consistency", "FAIL" if problems else "PASS", "; ".join(problems) if problems else "manifest matches model configs")


def check_camera_config() -> Check:
    path = ROOT / os.getenv("CAMERA_CONFIG", "SED_1_Multi_Camera/configs/3_cameras.json")
    if not path.is_file():
        return Check("camera_config", "WARN", f"{path} missing: /streams/start will fail; /predict is unaffected", required=False)
    try:
        cameras = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return Check("camera_config", "FAIL", f"{path} is not valid JSON: {exc}", required=False)
    count = len(cameras) if isinstance(cameras, list) else len(cameras.get("cameras", []))
    return Check("camera_config", "PASS", f"{path.name}: {count} camera entries (sources must be mounted/reachable)", required=False)


def port_in_use(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(1.0)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def check_ports(expect_free: bool) -> list[Check]:
    out = []
    for port in PORTS:
        used = port_in_use(port)
        if expect_free:
            out.append(Check(f"port:{port}", "FAIL" if used else "PASS", "in use by another process: stop it or change the port" if used else "free"))
        else:
            out.append(Check(f"port:{port}", "PASS", "in use (service running?)" if used else "free", required=False))
    return out


def check_writable(paths: list[Path]) -> list[Check]:
    out = []
    for path in paths:
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".fdd3_write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            out.append(Check(f"writable:{path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}", "PASS", "writable"))
        except OSError as exc:
            out.append(Check(f"writable:{path}", "FAIL", f"{type(exc).__name__}: {exc}"[:200]))
    return out


def check_disk(path: Path = ROOT, minimum: int = MIN_FREE_BYTES) -> Check:
    free = shutil.disk_usage(path).free
    return Check("disk_free", "PASS" if free >= minimum else "WARN",
                 f"{free / 1e9:.1f} GB free (planning minimum {minimum / 1e9:.0f} GB; incident growth not yet benchmarked)", required=False)


def run_checks(expect_ports_free: bool = False, model_path: Optional[Path] = None) -> list[Check]:
    model = model_path or Path(os.getenv("INDUSTRIX_MODEL_PATH", ROOT / "Backend/best.pt"))
    model = model if model.is_absolute() else ROOT / model
    checks = [check_python(), *check_imports(REQUIRED_IMPORTS, True), *check_imports(OPTIONAL_IMPORTS, False),
              check_model(model), check_openvino_export()]
    for fn in (check_watchdog_config, check_taxonomy, check_camera_config):
        try:
            checks.append(fn())
        except Exception as exc:  # a broken checker must be visible, not fatal
            checks.append(Check(fn.__name__.removeprefix("check_"), "FAIL", f"checker error {type(exc).__name__}: {exc}"[:300]))
    data_dir = Path(os.getenv("INCIDENT_DATABASE", "Backend/data/events.db"))
    data_dir = (data_dir if data_dir.is_absolute() else ROOT / data_dir).parent
    checks += check_ports(expect_ports_free) + check_writable([data_dir, ROOT / "EAP_5_Watchdog/runtime"]) + [check_disk()]
    return checks


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--expect-ports-free", action="store_true", help="fail if 8000/8501 are already in use")
    args = parser.parse_args(argv)
    os.environ.setdefault("YOLO_OFFLINE", "true")
    try:
        checks = run_checks(args.expect_ports_free)
    except Exception as exc:
        print(f"VALIDATION ERROR: {type(exc).__name__}: {exc}")
        return 2
    for c in checks:
        print(f"{c.status:<5} {c.name:<28} {c.detail}")
    failed = [c for c in checks if c.required and c.status == "FAIL"]
    print(f"RESULT: {'PASS' if not failed else 'FAIL'} ({len(checks)} checks, {len(failed)} required failures, "
          f"{sum(c.status == 'WARN' for c in checks)} warnings)")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(dict(result="PASS" if not failed else "FAIL", python=sys.executable,
                                             checks=[asdict(c) for c in checks]), indent=2), encoding="utf-8")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
