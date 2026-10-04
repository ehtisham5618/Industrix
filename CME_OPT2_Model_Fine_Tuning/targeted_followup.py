"""CME-OPT2-C: lower-rate AdamW and explicit weak-class focal weighting."""
import csv
import json
import time
from pathlib import Path
import torch
import yaml
from ultralytics import YOLO
from ultralytics.utils import SETTINGS
from weighted_trainer import HazardWeightedTrainer
from workflow import prepare, environment, write_json, digest, metrics
from local_dataset import prepare_local

TASK=Path(__file__).resolve().parent
NAME="cme_opt2_C_targeted_focal_cosine"


def run(work):
    work=Path(work).resolve()
    SETTINGS.update({"mlflow":False,"wandb":False,"comet":False})
    assert torch.cuda.is_available()
    data,names=prepare_local(work)
    config=yaml.safe_load((TASK / "config.yaml").read_text());config.pop("model")
    config.update(optimizer="AdamW",lr0=.001,warmup_bias_lr=0.,data=str(data),device=0,
                  project=str(work / "runs"),name=NAME,cls=.5)
    reports=work / "reports";reports.mkdir(exist_ok=True)
    model=YOLO(str(work / "baseline.pt"));assert list(model.names.values())==names
    rates=[]
    def record(trainer):
        row={"epoch":trainer.epoch+1,**{f"lr_pg{i}":g["lr"] for i,g in enumerate(trainer.optimizer.param_groups)}}
        if rates and rates[-1]["epoch"]==row["epoch"]:return
        rates.append(row)
        with (reports / f"{NAME}_lr.csv").open("w",newline="") as stream:
            writer=csv.DictWriter(stream,fieldnames=list(row));writer.writeheader();writer.writerows(rates)
        assert torch.isfinite(trainer.tloss).all()
        print("CME-OPT2-C EPOCH",row,"LOSSES",trainer.tloss.tolist(),flush=True)
    model.add_callback("on_fit_epoch_end",record)
    start=time.time();model.train(trainer=HazardWeightedTrainer,**config)
    run_dir=work / "runs" / NAME
    history=list(csv.DictReader((run_dir / "results.csv").open()))
    best=max(range(len(history)),key=lambda i:float(history[i]["metrics/mAP50-95(B)"]))
    contract={"run_label":"C","run_name":NAME,"starting_checkpoint":"cme1-expanded-12class-v1 (baseline.pt)",
              "starting_checkpoint_sha256":digest(work / "baseline.pt"),"dataset_yaml":str(data),
              "dataset_version":"combined-12class-v3-hardnegative","names":names,"best":str(run_dir / "weights/best.pt"),
              "last":str(run_dir / "weights/last.pt"),"run_dir":str(run_dir),"config":config,"focal_gamma":1.5,"focal_alpha":.25,
              "class_weights":{"chemical hazard":4.,"smoke":2.,"others":1.},"requested_epochs":50,"completed_epochs":len(history),
              "best_epoch":int(history[best]["epoch"]),"elapsed_seconds":time.time()-start,
              "best_sha256":digest(run_dir / "weights/best.pt"),"environment":environment(),
              "reason":"B selected validation chemical AP50=45.4% remains weak despite overall 77.3%; use AdamW lr=.001 and no large bias warmup to reduce pretrained-head disruption, focal class weights 4 chemical / 2 smoke to direct weak-class learning; no test feedback",
              "selection":"Best validation mAP50-95 within C; final cross-run selection uses validation only",
              "execution_sources_sha256":{name:digest(TASK / name) for name in ("workflow.py","focal_trainer.py","config.yaml","modal_runner.py","weighted_trainer.py","targeted_followup.py","candidate_runner.py","local_dataset.py")}}
    contract["validation"]=metrics(contract["best"],data,reports,"C_selected_validation","val")
    write_json(reports / f"{NAME}_contract.json",contract)
    return {"completed_epochs":len(history),"validation":contract["validation"]}


if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument("--work",type=Path,required=True)
    args=parser.parse_args();print(json.dumps(run(args.work),indent=2))
