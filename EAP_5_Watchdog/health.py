"""Loopback HTTP and process-liveness health checks (stdlib only, bounded)."""
from __future__ import annotations

import http.client
import json
import socket
import time
from typing import Callable, Optional
from urllib.parse import urlparse

from .config import HealthCheck
from .contracts import HealthResult


def check_http(spec: HealthCheck) -> HealthResult:
    """GET spec.url with a hard timeout; healthy only if status/body/JSON expectations all hold."""
    url = urlparse(spec.url)
    started = time.perf_counter()
    conn = http.client.HTTPConnection(url.hostname, url.port or 80, timeout=spec.timeout_seconds)
    try:
        conn.request("GET", url.path or "/", headers={"Accept": "application/json, text/plain"})
        response = conn.getresponse()
        body = response.read(spec.max_body_bytes + 1)
        latency = (time.perf_counter() - started) * 1000
        if len(body) > spec.max_body_bytes:
            return HealthResult(ok=False, kind="http", status_code=response.status, latency_ms=latency,
                                detail="health body exceeds limit")
        if response.status != spec.expect_status:
            return HealthResult(ok=False, kind="http", status_code=response.status, latency_ms=latency,
                                detail=f"expected HTTP {spec.expect_status}")
        if spec.expect_body is not None and body.decode("utf-8", "replace").strip() != spec.expect_body:
            return HealthResult(ok=False, kind="http", status_code=response.status, latency_ms=latency,
                                detail="unexpected health body")
        if spec.expect_json_true:
            try:
                payload = json.loads(body)
            except (json.JSONDecodeError, UnicodeDecodeError):
                return HealthResult(ok=False, kind="http", status_code=response.status, latency_ms=latency,
                                    detail="malformed JSON health response")
            if not isinstance(payload, dict) or payload.get(spec.expect_json_true) is not True:
                return HealthResult(ok=False, kind="http", status_code=response.status, latency_ms=latency,
                                    detail=f"'{spec.expect_json_true}' is not true")
        return HealthResult(ok=True, kind="http", status_code=response.status, latency_ms=latency, detail="ok")
    except (socket.timeout, TimeoutError):
        return HealthResult(ok=False, kind="http", detail=f"timeout after {spec.timeout_seconds}s")
    except (ConnectionError, http.client.HTTPException, OSError) as exc:
        return HealthResult(ok=False, kind="http", detail=f"{type(exc).__name__}")
    finally:
        conn.close()


def check(spec: HealthCheck, process_alive: Optional[bool],
          http_checker: Callable[[HealthCheck], HealthResult] = check_http) -> HealthResult:
    """A dead owned process is unhealthy without probing; process-kind checks use liveness only."""
    if process_alive is False:
        return HealthResult(ok=False, kind="process", detail="managed process has exited")
    if spec.kind == "process":
        return HealthResult(ok=bool(process_alive), kind="process", detail="alive" if process_alive else "not running")
    return http_checker(spec)
