"""Detached recovery worker for official A, retaining the ten-minute idle rule."""
from pathlib import Path
import sys
import modal
if Path("/opt/cme_opt2").exists():
    sys.path.insert(0,"/opt/cme_opt2")
from modal_runner import image,volume
app=modal.App("industirx-cme-opt2-resume")


@app.function(image=image,gpu="A10G",volumes={"/work":volume},timeout=14400,cpu=8,memory=32768,
              scaledown_window=600,min_containers=0)
def restore():
    import sys,subprocess,threading
    sys.path.insert(0,"/opt/cme_opt2")
    from gpu_idle_watchdog import watch
    process=subprocess.Popen([sys.executable,"-u","/opt/cme_opt2/resume_official.py","--work","/work"],
                             stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    stop=threading.Event()
    threading.Thread(target=watch,args=(process,stop),daemon=True).start()
    try:
        with Path("/work/reports/resume_terminal.txt").open("a") as stream:
            for line in process.stdout:
                print(line,end="",flush=True);stream.write(line);stream.flush()
        code=process.wait();stop.set()
        if code:raise RuntimeError("Official A recovery failed; terminal evidence retained")
        return {"completed":True}
    finally:
        volume.commit()


@app.local_entrypoint()
def main():
    print(restore.remote())
