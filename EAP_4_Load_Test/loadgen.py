"""Closed-loop HTTP load generator against the real POST /predict.

`concurrency` worker threads each keep one persistent connection and at most one
request in flight, so in-flight work is bounded by construction. An optional
global rate limit spaces request starts. Response bodies are read with a size cap
and validated against the EAP-2 /predict contract and the verified class map.
"""
from __future__ import annotations

import http.client
import json
import random
import socket
import threading
import time
import uuid
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

from .config import LoadTestConfig
from .metrics import RequestMetrics

MAX_RESPONSE_BYTES = 1 << 20


def multipart(path: Path) -> tuple[bytes, str]:
    boundary = uuid.uuid5(uuid.NAMESPACE_URL, str(path)).hex
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{Path(path).name}\"\r\n"
            f"Content-Type: image/png\r\n\r\n").encode()
    return head + Path(path).read_bytes() + f"\r\n--{boundary}--\r\n".encode(), f"multipart/form-data; boundary={boundary}"


def default_validator() -> Callable[[dict], None]:
    """Validate with the EAP-2 contract and committed class map (no new contract)."""
    from EAP_2_CI_Model_Regression import gate
    manifest = gate.load_manifest(Path(__file__).resolve().parents[1] /
                                  "EAP_2_CI_Model_Regression/baselines/cme-opt2-focal-cosine-12class-v1.json")

    def validate(payload: dict) -> None:
        response = gate.PredictResponse.model_validate(payload)
        for item in response.detections:
            if manifest.class_map.get(item.class_id) != item.class_name:
                raise ValueError(f"unexpected class {item.class_id}:{item.class_name}")
    return validate


class RatePacer:
    def __init__(self, rps: Optional[float], clock: Callable[[], float]):
        self.interval = 1 / rps if rps else 0.0
        self.clock = clock
        self._next = None
        self._lock = threading.Lock()

    def wait(self, stop: threading.Event) -> bool:
        if not self.interval:
            return not stop.is_set()
        with self._lock:
            now = self.clock()
            slot = now if self._next is None or self._next < now else self._next
            self._next = slot + self.interval
        delay = slot - self.clock()
        return not stop.wait(delay) if delay > 0 else not stop.is_set()


class LoadGenerator:
    def __init__(self, cfg: LoadTestConfig, metrics: RequestMetrics, start_time: float, end_time: float,
                 clock: Callable[[], float] = time.monotonic, validator: Optional[Callable[[dict], None]] = None):
        self.cfg, self.metrics, self.clock = cfg, metrics, clock
        self.start_time, self.end_time = start_time, end_time
        self.validate = validator or default_validator()
        self.stop_event = threading.Event()
        self.pacer = RatePacer(cfg.requests_per_second, clock)
        self.bodies = [multipart(Path(p)) for p in cfg.fixtures]
        url = urlparse(cfg.target_url)
        self.host, self.port, self.https = url.hostname, url.port or (443 if url.scheme == "https" else 80), url.scheme == "https"
        self.threads: list[threading.Thread] = []
        self.in_flight = 0
        self.max_in_flight_seen = 0
        self._lock = threading.Lock()

    def _connection(self):
        cls = http.client.HTTPSConnection if self.https else http.client.HTTPConnection
        return cls(self.host, self.port, timeout=self.cfg.request_timeout_seconds)

    def start(self) -> None:
        for index in range(self.cfg.concurrency):
            thread = threading.Thread(target=self._worker, args=(index,), name=f"eap4-worker-{index}", daemon=True)
            self.threads.append(thread)
            thread.start()

    def stop(self) -> None:
        self.stop_event.set()

    def join(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        for thread in self.threads:
            thread.join(max(0.0, deadline - time.monotonic()))
        return not any(t.is_alive() for t in self.threads)

    def _worker(self, index: int) -> None:
        rng = random.Random(self.cfg.seed * 1000 + index)  # deterministic fixture order per worker
        conn = self._connection()
        try:
            while not self.stop_event.is_set() and self.clock() < self.end_time:
                if not self.pacer.wait(self.stop_event) or self.clock() >= self.end_time:
                    break
                body, content_type = self.bodies[rng.randrange(len(self.bodies))]
                warmup = self.clock() - self.start_time < self.cfg.warmup_seconds
                self.metrics.schedule()
                outcome, status, latency, reset = self._send(conn, body, content_type)
                self.metrics.record(outcome, latency, status, warmup)
                if reset:
                    conn.close()
                    conn = self._connection()
        finally:
            conn.close()

    def _send(self, conn, body: bytes, content_type: str):
        with self._lock:
            self.in_flight += 1
            self.max_in_flight_seen = max(self.max_in_flight_seen, self.in_flight)
        started = time.perf_counter()
        try:
            conn.request("POST", self.cfg.endpoint, body=body, headers={"Content-Type": content_type})
            response = conn.getresponse()
            data = response.read(MAX_RESPONSE_BYTES + 1)
            latency = (time.perf_counter() - started) * 1000
            if len(data) > MAX_RESPONSE_BYTES:
                return "invalid_response", response.status, latency, True
            if response.status != 200:
                return "http_error", response.status, latency, response.will_close
            try:
                self.validate(json.loads(data))
            except (ValueError, TypeError) as exc:  # pydantic ValidationError subclasses ValueError
                return "invalid_response", response.status, latency, response.will_close
            return "success", response.status, latency, response.will_close
        except (socket.timeout, TimeoutError):
            return "timeout", None, None, True
        except (ConnectionError, http.client.HTTPException, OSError):
            return "connection_error", None, None, True
        finally:
            with self._lock:
                self.in_flight -= 1
