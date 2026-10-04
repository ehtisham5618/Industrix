"""Stop a running worker if the GPU is continuously idle for ten minutes."""
import subprocess
import time


def watch(process, stop_event, idle_seconds=600, poll_seconds=15):
    idle_since = None
    while not stop_event.wait(poll_seconds):
        if process.poll() is not None:
            return
        try:
            reading = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                text=True, timeout=10)
            idle = all(int(value.strip()) == 0 for value in reading.splitlines())
        except (subprocess.SubprocessError, ValueError):
            # Unknown utilization is not evidence of continuous inactivity.
            idle_since = None
            continue
        if not idle:
            idle_since = None
        elif idle_since is None:
            idle_since = time.monotonic()
        elif time.monotonic() - idle_since >= idle_seconds:
            print("CME-OPT2 idle watchdog: GPU idle continuously for 600 seconds; stopping worker.", flush=True)
            process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
            return
