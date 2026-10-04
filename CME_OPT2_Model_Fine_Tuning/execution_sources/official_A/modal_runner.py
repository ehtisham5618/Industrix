"""GPU execution on the user's configured Modal account (no embedded tokens)."""
from pathlib import Path
import modal

TASK = Path(__file__).resolve().parent
app = modal.App("industirx-cme-opt2")
volume = modal.Volume.from_name("industirx-cme-opt2", create_if_missing=True)
image = (modal.Image.debian_slim(python_version="3.11")
         .apt_install("libgl1", "libglib2.0-0")
         .pip_install("ultralytics==8.4.24", "torch==2.10.0", "torchvision==0.25.0", "mlflow==2.22.2")
         .add_local_file(TASK.parent / "Experiment_Tracking/scripts/mlflow_utils.py", remote_path="/opt/cme_opt2/mlflow_utils.py")
         .add_local_dir(TASK, remote_path="/opt/cme_opt2",
                        ignore=lambda p: any(part in {"runtime", "reports", "__pycache__"} for part in p.parts)))


@app.function(image=image, gpu="A10G", volumes={"/work": volume}, timeout=14400, cpu=8, memory=32768,
              scaledown_window=600, min_containers=0)
def execute(mode: str):
    import sys
    import subprocess
    import threading
    sys.path.insert(0, "/opt/cme_opt2")
    if mode == "probe":
        import torch, ultralytics
        result = {"gpu": torch.cuda.get_device_name(), "vram": torch.cuda.get_device_properties(0).total_memory,
                  "torch": torch.__version__, "ultralytics": ultralytics.__version__}
        print(result, flush=True)
        return result
    try:
        reports = Path("/work/reports")
        reports.mkdir(exist_ok=True)
        with (reports / f"{mode}_terminal.txt").open("w") as log:
            process = subprocess.Popen([sys.executable, "-u", "/opt/cme_opt2/workflow.py", mode, "--work", "/work"],
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            from gpu_idle_watchdog import watch
            stop_event = threading.Event()
            watchdog = threading.Thread(target=watch, args=(process, stop_event), daemon=True)
            watchdog.start()
            for line in process.stdout:
                print(line, end="", flush=True)
                log.write(line)
                log.flush()
            exit_code = process.wait()
            stop_event.set()
            if exit_code:
                raise RuntimeError(f"CME-OPT2 {mode} failed; actual terminal output retained")
        return {"mode": mode, "completed": True, "artifacts": "industirx-cme-opt2:/reports"}
    finally:
        volume.commit()


@app.local_entrypoint()
def main(mode: str = "probe"):
    print(execute.remote(mode))
