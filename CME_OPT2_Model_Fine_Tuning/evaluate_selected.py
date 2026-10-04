"""One final test comparison after validation-only selection across tracked runs."""
import csv
import json
from pathlib import Path
from workflow import prepare, metrics, qualitative, write_json, digest
from mlflow_utils import configure_tracking
from local_dataset import prepare_local


def run(work):
    work = Path(work).resolve()
    data, _ = prepare_local(work)
    reports = work / "reports"
    selected = json.loads((work / "training_contract.json").read_text())
    all_runs = json.loads((reports / "all_training_runs.json").read_text())
    assert all_runs["test_used_for_selection"] is False
    assert digest(selected["best"]) == selected["best_sha256"]
    baseline = metrics(work / "baseline.pt", data, reports, "baseline_test", "test")
    candidate = metrics(selected["best"], data, reports, "candidate_test", "test")
    gates = {"chemical_ap50": candidate["per_class"]["chemical hazard"]["ap50"] >= .65,
             "overall_map50": candidate["overall"]["map50"] >= .72}
    report = {"baseline": baseline, "candidate": candidate, "gates": gates, "accepted": all(gates.values()),
              "historical_baseline_chemical_ap50": .49132694242889996,
              "historical_baseline_split": "val (53 chemical annotations); fresh same-test comparison above",
              "selection": selected["selection"], "test_chemical_objects": 4, "training": selected,
              "all_training_runs": all_runs}
    qualitative(work, data, selected["best"], reports)
    write_json(reports / "evaluation.json", report)
    mlflow = configure_tracking(work / "mlruns")
    ids = {}
    for contract in all_runs["runs"]:
        run_name = Path(contract["run_dir"]).name
        is_selected = run_name == all_runs["selected_run"]
        label = contract.get("run_label", "A")
        with mlflow.start_run(run_name=f"CME-OPT2-{label}: YOLOv8s focal cosine") as tracking_run:
            mlflow.set_tags({"task": "CME-OPT2", "sprint": "Sprint 4", "experiment_type": "model_finetuning",
                             "selected": str(is_selected), "status": ("accepted" if report["accepted"] else "target_shortfall") if is_selected else "not_selected_validation"})
            mlflow.log_params({**contract["config"], "starting_checkpoint": contract.get("starting_checkpoint", "yolov8s.pt"),
                               "dataset_version": contract["dataset_version"], "focal_gamma": 1.5, "focal_alpha": .25,
                               "completed_epochs": contract["completed_epochs"], "best_epoch": contract["best_epoch"],
                               "best_sha256": contract["best_sha256"], "selection": selected["selection"],
                               "focal_class_weights":json.dumps(contract.get("class_weights", "all 1")),
                               "reason": contract.get("reason", "Official requested COCO initialization and cls=.5")})
            validation = contract["validation"]
            mlflow.log_metrics({**{f"validation_{k}":v for k,v in validation["overall"].items()},
                                "validation_chemical_ap50": validation["per_class"]["chemical hazard"]["ap50"],
                                "validation_smoke_ap50": validation["per_class"]["smoke"]["ap50"]})
            if is_selected:
                mlflow.log_metrics({**{f"test_{k}":v for k,v in candidate["overall"].items()},
                                    "test_chemical_ap50": candidate["per_class"]["chemical hazard"]["ap50"],
                                    "test_smoke_ap50": candidate["per_class"]["smoke"]["ap50"]})
                report["mlflow_run_id"] = tracking_run.info.run_id
            rates = list(csv.DictReader((reports / f"{run_name}_lr.csv").open()))
            mlflow.log_param("actual_final_lr", rates[-1]["lr_pg0"])
            mlflow.log_artifact(str(Path(contract["run_dir"]) / "results.csv"))
            mlflow.log_artifact(str(Path(contract["run_dir"]) / "args.yaml"))
            mlflow.log_artifacts(str(reports), "reports")
            ids[run_name] = tracking_run.info.run_id
    report["mlflow_run_ids"] = ids
    write_json(reports / "evaluation.json", report)
    return {"gates": gates, "accepted": report["accepted"], "selected": all_runs["selected_run"], "mlflow_run_ids": ids}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(); parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args(); print(json.dumps(run(args.work), indent=2))
