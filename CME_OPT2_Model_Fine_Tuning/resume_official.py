"""Restore official A after an infrastructure disconnect, without changing its config."""
import csv
import json
import shutil
import time
from pathlib import Path
import torch
import yaml
from ultralytics import YOLO
from ultralytics.utils import SETTINGS
from focal_trainer import FocalDetectionTrainer
from workflow import prepare, metrics, environment, digest, write_json

TASK = Path(__file__).resolve().parent
NAME = "cme_opt2_yolov8s_focal_cosine"


def run(work):
    work = Path(work).resolve()
    SETTINGS.update({"mlflow": False, "wandb": False, "comet": False})
    data, names = prepare(work)
    reports, run_dir = work / "reports", work / "runs" / NAME
    checkpoint = run_dir / "weights/last.pt"
    saved = torch.load(checkpoint, map_location="cpu", weights_only=False)
    expected = yaml.safe_load((TASK / "config.yaml").read_text())
    for key in ("epochs", "patience", "batch", "imgsz", "optimizer", "lr0", "lrf", "cos_lr", "seed"):
        assert saved["train_args"][key] == expected[key], f"Resume configuration drift: {key}"
    assert saved["optimizer"] is not None and saved["scaler"] is not None
    resume_epoch = saved["epoch"] + 1
    backup = work / f"official_A_resume_epoch_{resume_epoch}.pt"
    if not backup.exists(): shutil.copy2(checkpoint, backup)
    resume_sha = digest(backup)
    rates_path = reports / f"{NAME}_lr.csv"
    rates = list(csv.DictReader(rates_path.open()))
    rates = [{"epoch": int(row["epoch"]), **{k:float(v) for k,v in row.items() if k != "epoch"}} for row in rates]
    def record(trainer):
        row = {"epoch": trainer.epoch+1, **{f"lr_pg{i}":g["lr"] for i,g in enumerate(trainer.optimizer.param_groups)}}
        if rates and rates[-1]["epoch"] == row["epoch"]: return
        rates.append(row)
        with rates_path.open("w", newline="") as stream:
            writer=csv.DictWriter(stream, fieldnames=list(row)); writer.writeheader(); writer.writerows(rates)
        assert torch.isfinite(trainer.tloss).all()
        print("CME-OPT2-A RESUMED EPOCH", row, "LOSSES", trainer.tloss.tolist(), flush=True)
    model = YOLO(str(checkpoint))
    model.add_callback("on_fit_epoch_end", record)
    start = time.time()
    model.train(resume=True, trainer=FocalDetectionTrainer)
    history = list(csv.DictReader((run_dir / "results.csv").open()))
    epochs = [int(row["epoch"]) for row in history]
    assert epochs == list(range(1,len(epochs)+1)) and len(history) <= 50
    best_index = max(range(len(history)), key=lambda i:float(history[i]["metrics/mAP50-95(B)"]))
    contract = {"run_label":"A", "run_name":NAME, "starting_checkpoint":"yolov8s.pt", "dataset_yaml":str(data),
                "dataset_version":"combined-12class-v3-hardnegative", "names":names,
                "best":str(run_dir / "weights/best.pt"), "last":str(run_dir / "weights/last.pt"), "run_dir":str(run_dir),
                "config":{k:v for k,v in saved["train_args"].items() if k in expected} | {"data":str(data),"device":0,"project":str(work / "runs"),"name":NAME},
                "focal_gamma":1.5,"focal_alpha":.25,"requested_epochs":50,"completed_epochs":len(history),
                "best_epoch":int(history[best_index]["epoch"]), "elapsed_seconds":float(history[-1]["time"]),
                "resume_elapsed_seconds":time.time()-start, "best_sha256":digest(run_dir / "weights/best.pt"),"environment":environment(),
                "resume":{"completed_before_disconnect":resume_epoch,"checkpoint_sha256":resume_sha,"checkpoint_backup":str(backup),
                          "optimizer_and_scaler_restored":True,"parameters_unchanged":True,
                          "limitation":"Augmentation RNG/early-stopping in-memory state reinitializes on upstream resume; not bitwise equivalent to uninterrupted execution"},
                "reason":"Official requested configuration; resumed after Modal client network timeout",
                "selection":"Best validation mAP50-95 within official A; no test feedback",
                "execution_sources_sha256":{name:digest(TASK / name) for name in ("workflow.py","focal_trainer.py","config.yaml","modal_runner.py","resume_official.py","resume_runner.py")},
                "initial_execution_sources_sha256":{name:digest(TASK / "execution_sources/official_A" / name) for name in ("workflow.py","focal_trainer.py","config.yaml","modal_runner.py")}}
    contract["validation"] = metrics(contract["best"],data,reports,"A_selected_validation","val")
    write_json(reports / f"{NAME}_contract.json",contract)
    write_json(work / "training_contract.json",contract)
    return {"completed_epochs":len(history),"validation":contract["validation"]}


if __name__ == "__main__":
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument("--work",type=Path,required=True)
    args=parser.parse_args();print(json.dumps(run(args.work),indent=2))
