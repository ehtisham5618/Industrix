"""Periodic resource profiler for the *service* process (not the load generator).

Samples are streamed to JSONL as they are taken; only a small bounded tail is kept
in memory. Unavailable metrics are written as null with the reason recorded once.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

import psutil


def find_listening_pid(target_url: str) -> Optional[int]:
    port = urlparse(target_url).port or (443 if target_url.startswith("https") else 80)
    try:
        for conn in psutil.net_connections(kind="tcp"):
            if conn.status == psutil.CONN_LISTEN and conn.laddr and conn.laddr.port == port and conn.pid:
                return conn.pid
    except (psutil.AccessDenied, OSError):
        return None
    return None


def _container_stats(name: str, timeout: float = 10) -> dict:
    out = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{json .}}", name],
                         capture_output=True, text=True, timeout=timeout)
    if out.returncode:
        raise RuntimeError(out.stderr.strip()[:200])
    stats = json.loads(out.stdout.strip().splitlines()[0])
    inspect = subprocess.run(["docker", "inspect", name, "--format",
                              "{{.HostConfig.Memory}} {{.RestartCount}} {{.State.Status}}"],
                             capture_output=True, text=True, timeout=timeout).stdout.split()
    return dict(container_mem_usage=stats.get("MemUsage"), container_mem_percent=stats.get("MemPerc"),
                container_cpu_percent=stats.get("CPUPerc"),
                container_mem_limit_bytes=int(inspect[0]) if inspect and inspect[0].isdigit() and int(inspect[0]) else None,
                container_restart_count=int(inspect[1]) if len(inspect) > 1 and inspect[1].isdigit() else None,
                container_status=inspect[2] if len(inspect) > 2 else None)


class ServiceProfiler:
    """Samples the service process every `interval` seconds into `path` (JSONL)."""

    def __init__(self, path: Path, interval: float, target_url: str, pid: Optional[int] = None,
                 container: Optional[str] = None, clock: Callable[[], float] = time.monotonic,
                 extra: Optional[Callable[[], dict]] = None, tail: int = 64):
        self.path, self.interval, self.target_url, self.container = Path(path), interval, target_url, container
        self.clock, self.extra = clock, extra
        self.pid = pid or find_listening_pid(target_url)
        self.process = psutil.Process(self.pid) if self.pid else None
        self.create_time = self.process.create_time() if self.process else None
        self.own = psutil.Process()
        self.tail = deque(maxlen=tail)
        self.samples = 0
        self.failures: list[dict] = []
        self.restarts: list[dict] = []
        self.unavailable: dict[str, str] = {}
        self.gaps: list[dict] = []
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._start = None
        self._last = None
        if self.process:
            self.process.cpu_percent(None)
        psutil.cpu_percent(None)

    def start(self, start_time: Optional[float] = None) -> None:
        self._start = start_time if start_time is not None else self.clock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._thread = threading.Thread(target=self._run, name="eap4-profiler", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 15) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)

    def _run(self) -> None:
        with self.path.open("a", encoding="utf-8") as stream:
            while not self._stop.is_set():
                try:
                    row = self.sample()
                    stream.write(json.dumps(row) + "\n")
                    stream.flush()
                    self.tail.append(row)
                    self.samples += 1
                except Exception as exc:  # never lose the main run because of one bad sample
                    self.failures.append(dict(elapsed_s=self.clock() - self._start, error=f"{type(exc).__name__}: {exc}"[:300]))
                    if len(self.failures) > 1000:
                        del self.failures[:500]
                self._stop.wait(self.interval)

    def _note(self, key: str, reason: str) -> None:
        self.unavailable.setdefault(key, reason)

    def _resolve_restart(self) -> None:
        alive = self.process is not None and self.process.is_running() and self.process.create_time() == self.create_time
        if alive:
            return
        new_pid = find_listening_pid(self.target_url)
        event = dict(elapsed_s=self.clock() - self._start, old_pid=self.pid, new_pid=new_pid)
        self.restarts.append(event)
        self.pid = new_pid
        self.process = psutil.Process(new_pid) if new_pid else None
        self.create_time = self.process.create_time() if self.process else None
        if self.process:
            self.process.cpu_percent(None)

    def sample(self) -> dict:
        now = self.clock()
        elapsed = now - self._start
        if self._last is not None and now - self._last > 2.5 * self.interval:
            self.gaps.append(dict(start_s=self._last - self._start, end_s=elapsed, gap_s=now - self._last))
        self._last = now
        vm = psutil.virtual_memory()
        row = dict(elapsed_s=round(elapsed, 3), wall_time=time.time(), pid=self.pid,
                   system_cpu_percent=psutil.cpu_percent(None), system_mem_total_bytes=vm.total,
                   system_mem_available_bytes=vm.available, harness_rss_bytes=self.own.memory_info().rss)
        try:
            self._resolve_restart()
        except psutil.Error as exc:
            row["process_error"] = type(exc).__name__
        p = self.process
        if p is None:
            row.update(process_alive=False, rss_bytes=None, vms_bytes=None)
        else:
            try:
                with p.oneshot():
                    mem = p.memory_info()
                    children = p.children(recursive=True)
                    row.update(process_alive=True, rss_bytes=mem.rss, vms_bytes=mem.vms,
                               process_cpu_percent=p.cpu_percent(None), threads=p.num_threads(),
                               uptime_s=time.time() - p.create_time(), children=len(children))
                    if os.name == "nt":
                        row["handles"] = p.num_handles()
                        self._note("fds", "Windows: open handles recorded instead of file descriptors")
                    else:
                        row["fds"] = p.num_fds()
                child_rss = 0
                for child in children:
                    try:
                        child_rss += child.memory_info().rss
                    except psutil.Error:
                        pass
                row["children_rss_bytes"] = child_rss
            except psutil.Error as exc:
                row.update(process_alive=False, rss_bytes=None, process_error=type(exc).__name__)
        self._note("python_gc_tracemalloc", "Service runs in a separate process; Python GC/allocation stats are not observable externally")
        self._note("gpu", "CPU deployment; no GPU in use")
        if self.container:
            try:
                row.update(_container_stats(self.container))
            except Exception as exc:
                row["container_error"] = f"{type(exc).__name__}: {exc}"[:200]
        else:
            self._note("container", "Service not run in a container for this run")
        if self.extra:
            row.update(self.extra())
        return row

    def status(self) -> dict:
        return dict(samples=self.samples, sampling_failures=len(self.failures), failures_tail=self.failures[-10:],
                    restarts=self.restarts, gaps=self.gaps, unavailable=self.unavailable, pid=self.pid,
                    interval_seconds=self.interval, path=str(self.path))
