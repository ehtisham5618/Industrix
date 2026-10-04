"""Evaluation worker kept separate from the immutable training execution sources."""
from pathlib import Path
import sys
import modal
if Path("/opt/cme_opt2").exists():
    sys.path.insert(0,"/opt/cme_opt2")
from modal_runner import image, volume

app = modal.App("industirx-cme-opt2-evaluation")


@app.function(image=image, gpu="A10G", volumes={"/work":volume}, timeout=3600,
              cpu=8, memory=32768, scaledown_window=600, min_containers=0,region="us-east")
def evaluate():
    import sys, subprocess, threading
    sys.path.insert(0, "/opt/cme_opt2")
    from gpu_idle_watchdog import watch
    process = subprocess.Popen([sys.executable, "-u", "/opt/cme_opt2/evaluate_selected.py", "--work", "/work"],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    stop = threading.Event()
    threading.Thread(target=watch, args=(process,stop), daemon=True).start()
    try:
        with Path("/work/reports/evaluate_terminal.txt").open("w") as stream:
            for line in process.stdout:
                print(line,end="",flush=True); stream.write(line); stream.flush()
        code = process.wait(); stop.set()
        if code: raise RuntimeError("Final test evaluation failed; actual terminal evidence retained")
        return {"completed":True,"report":"industirx-cme-opt2:/reports/evaluation.json"}
    finally:
        volume.commit()


@app.local_entrypoint()
def main():
    print(evaluate.remote())
