"""FDD-3 post-deployment smoke test against RUNNING local services (loopback only).

python -m FDD_3_Deployment_Handoff.smoke_test [--backend http://127.0.0.1:8000] [--dashboard http://127.0.0.1:8501]

Checks: backend /health (model loaded), a real /predict on a bundled fixture (contract + class map),
a corrupt upload is rejected with 400, /system/status, /incidents, dashboard /_stcore/health.
Exit codes: 0 all pass, 1 a check failed, 3 a non-loopback target was given.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "assets" / "ife_ui3_fire.png"
CLASSES = {0: "baekra", 1: "color issues", 2: "contamination", 3: "cut", 4: "gray stitch", 5: "selvet", 6: "stain",
           7: "chemical hazard", 8: "fire", 9: "no helmet", 10: "smoke", 11: "water leak"}
LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def request(method: str, url: str, body: Optional[bytes] = None, ctype: Optional[str] = None,
            timeout: float = 30) -> tuple[Optional[int], bytes, str]:
    """Return (status or None, body, error). Never raises for HTTP/network errors."""
    req = urllib.request.Request(url, data=body, method=method, headers={"Content-Type": ctype} if ctype else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, response.read(1 << 20), ""
    except urllib.error.HTTPError as error:
        return error.code, error.read(1 << 16), ""
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return None, b"", f"{type(exc).__name__}: {getattr(exc, 'reason', exc)}"


def multipart(name: str, data: bytes) -> tuple[bytes, str]:
    boundary = "fdd3smoke"
    return ((f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
             f"Content-Type: image/png\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode(),
            f"multipart/form-data; boundary={boundary}")


def validate_predict(payload: dict) -> str:
    """Return '' when the /predict payload matches the documented contract, else the problem."""
    if not isinstance(payload.get("detections"), list):
        return "missing detections list"
    for det in payload["detections"]:
        if CLASSES.get(det.get("class_id")) != det.get("class_name"):
            return f"class {det.get('class_id')}:{det.get('class_name')} not in the 12-class map"
        conf = det.get("confidence")
        if not isinstance(conf, (int, float)) or not 0 <= conf <= 1:
            return f"confidence {conf!r} outside [0,1]"
        box = det.get("coordinates", {})
        if not all(isinstance(box.get(k), (int, float)) for k in ("x1", "y1", "x2", "y2")) or box["x2"] <= box["x1"] or box["y2"] <= box["y1"]:
            return f"invalid coordinates {box}"
    return ""


def run(backend: str, dashboard: Optional[str], timeout: float = 30) -> list[dict]:
    results = []

    def add(name: str, ok: bool, detail: str) -> None:
        results.append(dict(check=name, status="PASS" if ok else "FAIL", detail=detail))

    code, body, err = request("GET", backend + "/health", timeout=timeout)
    health = json.loads(body) if code == 200 else {}
    add("backend_health", code == 200 and health.get("model_loaded") is True,
        err or f"HTTP {code}; model_loaded={health.get('model_loaded')} classes={health.get('classes')}")
    code, body, err = request("POST", backend + "/predict", *multipart(FIXTURE.name, FIXTURE.read_bytes()), timeout=timeout)
    problem = err or (validate_predict(json.loads(body)) if code == 200 else f"HTTP {code}")
    count = len(json.loads(body)["detections"]) if code == 200 and not problem else None
    add("predict_valid_image", not problem and bool(count), problem or f"{count} detections, contract valid")
    code, body, err = request("POST", backend + "/predict", *multipart("corrupt.png", b"\x89PNG not an image"), timeout=timeout)
    add("predict_rejects_corrupt_upload", code == 400, err or f"HTTP {code}")
    for name, path in (("system_status", "/system/status"), ("incidents_api", "/incidents")):
        code, _, err = request("GET", backend + path, timeout=timeout)
        add(name, code == 200, err or f"HTTP {code}")
    if dashboard:
        code, body, err = request("GET", dashboard + "/_stcore/health", timeout=timeout)
        add("dashboard_health", code == 200 and body.strip() == b"ok", err or f"HTTP {code} body={body[:20]!r}")
    return results


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backend", default="http://127.0.0.1:8000")
    parser.add_argument("--dashboard", default="http://127.0.0.1:8501")
    parser.add_argument("--no-dashboard", action="store_true")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    for url in (args.backend, None if args.no_dashboard else args.dashboard):
        if url and urlparse(url).hostname not in LOOPBACK:
            print(f"refusing non-loopback target {url}: the smoke test is for local services only")
            return 3
    results = run(args.backend.rstrip("/"), None if args.no_dashboard else args.dashboard.rstrip("/"), args.timeout)
    for r in results:
        print(f"{r['status']:<5} {r['check']:<32} {r['detail']}")
    failed = [r for r in results if r["status"] == "FAIL"]
    print(f"SMOKE: {'PASS' if not failed else 'FAIL'} ({len(results) - len(failed)}/{len(results)} passed)")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(dict(result="PASS" if not failed else "FAIL", checks=results), indent=2), encoding="utf-8")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
