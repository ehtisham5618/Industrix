"""Owned child-process management and the single-instance lock.

Only processes this watchdog started (and their descendants) are ever signalled.
Nothing is matched by process name.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import psutil

IS_WINDOWS = os.name == "nt"


def port_owner(port: int) -> Optional[int]:
    """PID listening on a local TCP port, or None. Used to avoid starting a duplicate service."""
    try:
        for conn in psutil.net_connections(kind="tcp"):
            if conn.status == psutil.CONN_LISTEN and conn.laddr and conn.laddr.port == port:
                return conn.pid or -1
    except (psutil.AccessDenied, OSError):
        return None
    return None


class ManagedProcess:
    """One owned child with bounded, rotated stdout/stderr capture."""

    def __init__(self, name: str, command: list[str], cwd: Path, env: dict[str, str], log_dir: Path, max_log_bytes: int):
        self.name, self.command, self.cwd, self.env = name, command, cwd, env
        self.log_path = Path(log_dir) / f"{name}.out.log"
        self.max_log_bytes = max_log_bytes
        self.popen: Optional[subprocess.Popen] = None
        self._log = None
        self.create_time: Optional[float] = None

    @property
    def pid(self) -> Optional[int]:
        return self.popen.pid if self.popen else None

    def alive(self) -> bool:
        return self.popen is not None and self.popen.poll() is None

    def exit_code(self) -> Optional[int]:
        return self.popen.poll() if self.popen else None

    def _rotate(self) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if self.log_path.exists():
            previous = self.log_path.with_suffix(".log.1")
            previous.unlink(missing_ok=True)
            self.log_path.replace(previous)

    def start(self) -> int:
        if self.alive():
            raise RuntimeError(f"{self.name} already running as pid {self.pid}")
        self._rotate()
        self._log = self.log_path.open("ab")
        kwargs = dict(cwd=str(self.cwd), env={**os.environ, **self.env}, stdout=self._log, stderr=subprocess.STDOUT,
                      stdin=subprocess.DEVNULL, shell=False)
        if IS_WINDOWS:
            # Own process group, but SHARE the watchdog's console: CTRL_BREAK is only delivered to
            # processes attached to the sender's console (CREATE_NO_WINDOW would give a separate one).
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        try:
            self.popen = subprocess.Popen(self.command, **kwargs)
        except OSError:
            self._close_log()
            raise
        try:
            self.create_time = psutil.Process(self.popen.pid).create_time()
        except psutil.Error:
            self.create_time = None
        return self.popen.pid

    def log_oversized(self) -> bool:
        try:
            return self.log_path.stat().st_size > self.max_log_bytes
        except OSError:
            return False

    def stop(self, timeout: float) -> tuple[Optional[int], str]:
        """Graceful stop of the owned process tree; escalate to kill after `timeout`.

        Returns (exit code, mode) where mode is "graceful", "forced" or "already_exited"."""
        if self.popen is None:
            return None, "not_started"
        mode = "already_exited"
        try:
            if self.popen.poll() is None:
                mode = "graceful"
                descendants = self._descendants()
                try:
                    if IS_WINDOWS:
                        self.popen.send_signal(signal.CTRL_BREAK_EVENT)
                    else:
                        os.killpg(self.popen.pid, signal.SIGTERM)
                except (OSError, ProcessLookupError):
                    pass
                try:
                    self.popen.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    mode = "forced"
                    for proc in [psutil.Process(self.popen.pid), *descendants]:
                        try:
                            proc.kill()
                        except psutil.Error:
                            pass
                    self.popen.wait(timeout=10)
                gone, alive = psutil.wait_procs(descendants, timeout=5)
                for proc in alive:
                    try:
                        proc.kill()
                    except psutil.Error:
                        pass
            return self.popen.returncode, mode
        finally:
            self._close_log()

    def _descendants(self) -> list:
        try:
            parent = psutil.Process(self.popen.pid)
            if self.create_time and parent.create_time() != self.create_time:
                return []  # pid reused by an unrelated process: never touch it
            return parent.children(recursive=True)
        except psutil.Error:
            return []

    def _close_log(self) -> None:
        if self._log is not None:
            self._log.close()
            self._log = None


class LockError(RuntimeError):
    """Another live watchdog holds the lock."""


class InstanceLock:
    """Exclusive lock file holding {pid, create_time}. A stale lock (dead pid) is reclaimed;
    a live holder makes acquisition fail. Never terminates the holder."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.held = False

    def _holder_alive(self) -> Optional[dict]:
        try:
            info = json.loads(self.path.read_text(encoding="utf-8"))
            proc = psutil.Process(int(info["pid"]))
            if abs(proc.create_time() - float(info["create_time"])) < 1.0:
                return info
        except (OSError, ValueError, KeyError, json.JSONDecodeError, psutil.Error):
            return None
        return None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        me = dict(pid=os.getpid(), create_time=psutil.Process().create_time(), argv=sys.argv[:3])
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                holder = self._holder_alive()
                if holder:
                    raise LockError(f"another watchdog is running (pid {holder['pid']}); lock {self.path}")
                self.path.unlink(missing_ok=True)  # stale: holder is gone
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(me, stream)
            self.held = True
            return
        raise LockError(f"could not acquire lock {self.path}")

    def release(self) -> None:
        if self.held:
            try:
                info = json.loads(self.path.read_text(encoding="utf-8"))
                if int(info.get("pid", -1)) == os.getpid():
                    self.path.unlink(missing_ok=True)
            except (OSError, ValueError, json.JSONDecodeError):
                pass
            self.held = False


def wait_until(predicate, timeout: float, interval: float = 0.2) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()
