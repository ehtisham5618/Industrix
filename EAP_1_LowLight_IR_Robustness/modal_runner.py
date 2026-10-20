"""EAP-1 GPU execution on the user's configured Modal account (no embedded tokens).

Cost controls: zero minimum containers, 60 s scale-down after the call returns,
a hard function timeout, and the reused CME-OPT2 watchdog that stops the worker
after 600 continuous seconds at 0% GPU utilization.
"""
from pathlib import Path
import modal

TASK = Path(__file__).resolve().parent
ROOT = TASK.parent
app = modal.App("industirx-eap1")
source_volume = modal.Volume.from_name("industirx-cme-opt2")
volume = modal.Volume.from_name("industirx-eap1", create_if_missing=True)
image = (modal.Image.debian_slim(python_version="3.11")
         .apt_install("libgl1", "libglib2.0-0")
         .pip_install("ultralytics==8.4.24", "torch==2.10.0", "torchvision==0.25.0", "imagehash==4.3.2")
         .add_local_file(ROOT / "CME_OPT2_Model_Fine_Tuning/focal_trainer.py", remote_path="/opt/eap1/focal_trainer.py")
         .add_local_file(ROOT / "CME_OPT2_Model_Fine_Tuning/gpu_idle_watchdog.py", remote_path="/opt/eap1/gpu_idle_watchdog.py")
         .add_local_file(ROOT / "Backend/best.pt", remote_path="/opt/eap1/baseline.pt")
         .add_local_file(TASK / "configs/eap1_lowlight.yaml", remote_path="/opt/eap1/eap1_lowlight.yaml")
         .add_local_file(TASK / "degradations.py", remote_path="/opt/eap1/degradations.py")
         .add_local_file(TASK / "dataset_tools.py", remote_path="/opt/eap1/dataset_tools.py")
         .add_local_file(TASK / "evaluate.py", remote_path="/opt/eap1/evaluate.py")
         .add_local_file(TASK / "pipeline.py", remote_path="/opt/eap1/pipeline.py"))


@app.function(image=image, gpu="A10G", volumes={"/work": volume, "/source": source_volume}, timeout=3000,
              cpu=8, memory=32768, scaledown_window=60, min_containers=0)
def execute():
    import subprocess
    import sys
    import threading
    sys.path.insert(0, "/opt/eap1")
    from gpu_idle_watchdog import watch
    (Path("/work/reports")).mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-u", "/opt/eap1/pipeline.py", "--work", "/work", "--source-volume", "/source",
               "--baseline", "/opt/eap1/baseline.pt", "--config", "/opt/eap1/eap1_lowlight.yaml"]
    try:
        with Path("/work/reports/pipeline_terminal.txt").open("w") as log:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                                       cwd="/opt/eap1")
            stop = threading.Event()
            threading.Thread(target=watch, args=(process, stop), daemon=True).start()
            for line in process.stdout:
                print(line, end="", flush=True)
                log.write(line)
                log.flush()
            code = process.wait()
            stop.set()
        if code:
            raise RuntimeError(f"EAP-1 pipeline exited {code}; actual terminal output retained on volume")
        return {"completed": True, "artifacts": "industirx-eap1:/reports"}
    finally:
        volume.commit()


@app.local_entrypoint()
def main():
    print(execute.remote())
