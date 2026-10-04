"""Final controlled GPU variant and CPU-only model selection."""
from pathlib import Path
import sys
import modal
if Path("/opt/cme_opt2").exists():sys.path.insert(0,"/opt/cme_opt2")
from modal_runner import image,volume
app=modal.App("industirx-cme-opt2-targeted")


@app.function(image=image,gpu="A10G",volumes={"/work":volume},timeout=14400,cpu=8,memory=32768,
              scaledown_window=600,min_containers=0,region="us-east")
def train():
    import subprocess,threading
    from gpu_idle_watchdog import watch
    process=subprocess.Popen([sys.executable,"-u","/opt/cme_opt2/targeted_followup.py","--work","/work"],
                             stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    stop=threading.Event();threading.Thread(target=watch,args=(process,stop),daemon=True).start()
    try:
        with Path("/work/reports/targeted_terminal.txt").open("w") as stream:
            for line in process.stdout:
                print(line,end="",flush=True);stream.write(line);stream.flush()
        code=process.wait();stop.set()
        if code:raise RuntimeError("Controlled C failed; actual terminal evidence retained")
        return {"completed":True}
    finally:volume.commit()


@app.function(image=image,volumes={"/work":volume},timeout=600,cpu=2)
def select():
    import json
    from workflow import write_json
    work=Path("/work").resolve();reports=work / "reports"
    paths=[reports / (name+"_contract.json") for name in (
        "cme_opt2_yolov8s_focal_cosine","cme_opt2_B_expC_focal_cosine","cme_opt2_C_targeted_focal_cosine")]
    runs=[json.loads(p.read_text()) for p in paths]
    assert all(c["validation"]["split"]=="val" for c in runs)
    eligible=[c for c in runs if c["validation"]["overall"]["map50"]>=.72]
    chosen=max(eligible,key=lambda c:(c["validation"]["per_class"]["chemical hazard"]["ap50"],c["validation"]["overall"]["map50_95"])) if eligible else max(runs,key=lambda c:c["validation"]["overall"]["map50_95"])
    chosen["selection"]="Across A/B/C: retain candidates with validation mAP50>=.72 when any qualify; highest validation chemical AP50 then validation mAP50-95. If none qualify, highest validation mAP50-95. Each candidate uses its best validation mAP50-95 checkpoint. Test data unused."
    name=Path(chosen["run_dir"]).name
    write_json(reports / "all_training_runs.json",{"runs":runs,"selected_run":name,"criterion":chosen["selection"],"test_used_for_selection":False})
    write_json(work / "training_contract.json",chosen);volume.commit()
    return {"selected":name,"validation":chosen["validation"]}


@app.local_entrypoint()
def main(mode:str="train"):
    if mode=="select":print(select.remote())
    elif mode=="preflight":print(verify_archive.remote())
    else:
        print(verify_archive.remote())
        print(train.remote())


@app.function(image=image,volumes={"/work":volume},timeout=1800,cpu=4,region="us-east")
def verify_archive():
    from local_dataset import preflight
    result=preflight(Path("/work"));volume.commit();return result
