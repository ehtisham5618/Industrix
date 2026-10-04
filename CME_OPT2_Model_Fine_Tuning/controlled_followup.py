"""CME-OPT2-B: validation-motivated continuation of the registered 12-class model.

Official A stays immutable. B changes initialization and classification gain;
all requested scheduler, focal and training limits remain unchanged. Test data
does not inform these changes or model selection.
"""
import csv
import json
import time
from pathlib import Path
import torch
import yaml
from ultralytics import YOLO
from ultralytics.utils import SETTINGS
from focal_trainer import FocalDetectionTrainer
from workflow import prepare, environment, focal_sanity, write_json, digest, metrics

TASK = Path(__file__).resolve().parent
NAME = "cme_opt2_B_expC_focal_cosine"


def run(work):
    work = Path(work).resolve()
    SETTINGS.update({"mlflow": False, "wandb": False, "comet": False})
    assert torch.cuda.is_available()
    data, names = prepare(work)
    config = yaml.safe_load((TASK / "config.yaml").read_text())
    config.pop("model")
    config.update(data=str(data), device=0, project=str(work / "runs"), name=NAME, cls=2.0)
    reports = work / "reports"
    reports.mkdir(exist_ok=True)
    assert focal_sanity()["finite_loss"]
    model = YOLO(str(work / "baseline.pt"))
    assert list(model.names.values()) == names
    rates = []
    def record(trainer):
        row = {"epoch": trainer.epoch + 1, **{f"lr_pg{i}": g["lr"] for i,g in enumerate(trainer.optimizer.param_groups)}}
        if rates and rates[-1]["epoch"] == row["epoch"]: return
        rates.append(row)
        with (reports / f"{NAME}_lr.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(row)); writer.writeheader(); writer.writerows(rates)
        assert torch.isfinite(trainer.tloss).all()
        print("CME-OPT2-B EPOCH", row, "LOSSES", trainer.tloss.tolist(), flush=True)
    model.add_callback("on_fit_epoch_end", record)
    start = time.time()
    model.train(trainer=FocalDetectionTrainer, **config)
    run_dir = work / "runs" / NAME
    history = list(csv.DictReader((run_dir / "results.csv").open()))
    best_index = max(range(len(history)), key=lambda i: float(history[i]["metrics/mAP50-95(B)"]))
    contract = {"run_label": "B", "run_name": NAME, "starting_checkpoint": "cme1-expanded-12class-v1 (baseline.pt)",
                "starting_checkpoint_sha256": digest(work / "baseline.pt"), "dataset_yaml": str(data),
                "dataset_version": "combined-12class-v3-hardnegative", "names": names,
                "best": str(run_dir / "weights/best.pt"), "last": str(run_dir / "weights/last.pt"),
                "run_dir": str(run_dir), "config": config, "focal_gamma": 1.5, "focal_alpha": .25,
                "requested_epochs": 50, "completed_epochs": len(history), "best_epoch": int(history[best_index]["epoch"]),
                "elapsed_seconds": time.time()-start, "best_sha256": digest(run_dir / "weights/best.pt"), "environment": environment(),
                "reason": "Official A validation mAP50=16.4% at epoch 12 versus historical Experiment C=76.6%; retain a trained 12-class head and raise cls gain .5 to 2.0 to compensate alpha=.25; no test feedback",
                "selection": "Best validation mAP50-95 checkpoint within B; final cross-run selection is validation-only",
                "execution_sources_sha256": {name:digest(TASK / name) for name in ("workflow.py", "focal_trainer.py", "config.yaml", "modal_runner.py", "controlled_followup.py")}}
    contract["validation"] = metrics(contract["best"], data, reports, "B_selected_validation", "val")
    write_json(reports / f"{NAME}_contract.json", contract)
    return contract


def select(work):
    work = Path(work).resolve()
    reports = work / "reports"
    a = json.loads((reports / "cme_opt2_yolov8s_focal_cosine_contract.json").read_text())
    # A's detailed validation is in its original training contract.
    if "validation" not in a:
        a = json.loads((work / "training_contract.json").read_text())
    b = json.loads((reports / f"{NAME}_contract.json").read_text())
    eligible = [c for c in (a,b) if c["validation"]["overall"]["map50"] >= .72]
    chosen = max(eligible, key=lambda c:(c["validation"]["per_class"]["chemical hazard"]["ap50"], c["validation"]["overall"]["map50_95"])) if eligible else max((a,b), key=lambda c:c["validation"]["overall"]["map50_95"])
    chosen["selection"] = "Across completed A/B: require validation mAP50>=.72 if any candidate qualifies, then highest validation chemical AP50, tie-break by validation mAP50-95; otherwise highest validation mAP50-95. Each run uses its best validation mAP50-95 checkpoint. No test feedback."
    write_json(reports / "all_training_runs.json", {"runs": [a,b], "selected_run": Path(chosen["run_dir"]).name,
               "criterion": chosen["selection"], "test_used_for_selection": False})
    write_json(work / "training_contract.json", chosen)
    return {"selected": Path(chosen["run_dir"]).name, "validation": chosen["validation"]}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(); parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args(); print(json.dumps(run(args.work), indent=2))
