"""Build reports, verify deployment and append the existing CME-3 registries."""
import csv
import json
import shutil
import subprocess
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from ultralytics import YOLO
from workflow import digest, write_json

ROOT = Path(__file__).resolve().parent.parent
TASK = ROOT / "CME_OPT2_Model_Fine_Tuning"
REPORTS = TASK / "reports"
VERSION = "cme-opt2-focal-cosine-12class-v1"


def append(path, row, key):
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream); fields = reader.fieldnames; rows = list(reader)
    existing = next((r for r in rows if r[key] == row[key]), None)
    normalized = {field: str(row.get(field, "")) for field in fields}
    if existing:
        assert existing == normalized, f"Refusing to overwrite registered run: {row[key]}"
        return
    with path.open("a", encoding="utf-8", newline="") as stream:
        csv.DictWriter(stream, fieldnames=fields).writerow(normalized)


def main():
    report = json.loads((REPORTS / "evaluation.json").read_text())
    train, old, new = report["training"], report["baseline"], report["candidate"]
    initialization = json.loads((REPORTS / "initialization.json").read_text()) if (REPORTS / "initialization.json").exists() else {}
    run_name = Path(train["run_dir"]).name
    checkpoint = TASK / "runtime/runs" / run_name / "weights/best.pt"
    assert digest(checkpoint) == train["best_sha256"]
    backup = TASK / "runtime/baseline.pt"
    assert digest(backup) == old["checkpoint_sha256"]
    model = YOLO(str(checkpoint))
    assert list(model.names.values()) == train["names"]
    image = next((ROOT / "Hazard_Expansion/content_runtime/combined_dataset_augmented_v3/images/test").iterdir())
    prediction = model.predict(str(image), imgsz=640, device="cpu", verbose=False)
    assert len(prediction) == 1
    exported = False
    if train.get("selection"):
        current = ROOT / "Backend/best.pt"
        assert digest(current) in {old["checkpoint_sha256"], train["best_sha256"]}, "Deployment changed since baseline capture"
        shutil.copy2(checkpoint, current)
        deployed = YOLO(str(current))
        assert list(deployed.names.values()) == train["names"]
        assert len(deployed.predict(str(image), imgsz=640, device="cpu", verbose=False)) == 1
        assert digest(current) == train["best_sha256"]
        exported = True
    write_json(REPORTS / "deployment_verification.json", {"candidate_load": True, "classes": model.names,
               "inference": True, "exported": exported, "candidate_sha256": digest(checkpoint),
               "baseline_backup": str(backup.relative_to(ROOT)), "baseline_sha256": digest(backup),
               "deployed_sha256": digest(ROOT / "Backend/best.pt"), "idle_shutdown_seconds": 600})
    rows = []
    for name in train["names"]:
        a, b = old["per_class"][name], new["per_class"][name]
        rows.append({"class": name, **{f"baseline_{k}": v for k, v in a.items()},
                     **{f"candidate_{k}": v for k, v in b.items()}, "ap50_delta": b["ap50"] - a["ap50"],
                     "regression_gt_5pp": b["ap50"] - a["ap50"] < -.05})
    with (REPORTS / "per_class_comparison.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    x = np.arange(12)
    fig, ax = plt.subplots(figsize=(13, 5))
    ax.bar(x-.2, [r["baseline_ap50"] * 100 for r in rows], .4, label="Experiment C (test)")
    ax.bar(x+.2, [r["candidate_ap50"] * 100 for r in rows], .4, label="CME-OPT2 (test)")
    ax.set_xticks(x, train["names"], rotation=35, ha="right"); ax.set_ylabel("AP@50 (%)"); ax.legend(); fig.tight_layout()
    fig.savefig(REPORTS / "class_comparison.png", dpi=160); plt.close(fig)
    lr = list(csv.DictReader((REPORTS / f"{run_name}_lr.csv").open()))
    fig, ax = plt.subplots(figsize=(8, 4))
    for key in lr[0]:
        if key != "epoch": ax.plot([int(r["epoch"]) for r in lr], [float(r[key]) for r in lr], label=key)
    ax.set_xlabel("Actual completed epoch"); ax.set_ylabel("Learning rate"); ax.legend(); fig.tight_layout()
    fig.savefig(REPORTS / "learning_rate.png", dpi=160); plt.close(fig)
    run_dir = checkpoint.parent.parent
    shutil.copy2(run_dir / "results.csv", REPORTS / "training_results.csv")
    shutil.copy2(run_dir / "args.yaml", REPORTS / "training_args.yaml")
    for plot in ("results.png", "confusion_matrix.png", "confusion_matrix_normalized.png", "BoxPR_curve.png", "BoxF1_curve.png"):
        if (run_dir / plot).exists(): shutil.copy2(run_dir / plot, REPORTS / ("training_" + plot))
    chemical_delta = new["per_class"]["chemical hazard"]["ap50"] - old["per_class"]["chemical hazard"]["ap50"]
    lines = ["# CME-OPT2 Evaluation Report", "", f"Acceptance: **{'PASS' if report['accepted'] else 'FAIL — numerical target shortfall'}**.", "",
             f"Selected run: `{run_name}`. Official A uses COCO pretrained yolov8s.pt, SGD lr0=.01. B starts from registered Experiment C and raises cls gain .5 to 2.0. C uses the same Experiment C initialization with AdamW lr0=.001, zero bias warmup, cls=.5 and focal class weights chemical=4 / smoke=2 / others=1. All runs retain the same focal gamma/alpha, cosine factor, batch, image size, seed, maximum epochs and patience on CME-OPT1 v3.",
             "Dataset: 5,479 train / 777 validation / 334 test images; all 12 classes, 10,352 annotations. Evaluation files retain original SHA256 hashes.",
             "The original dataset already shares Roboflow source families across splits; CME-OPT1 introduced no new leakage. Generalization claims remain limited by inherited family overlap.", "",
             "Historical Experiment C chemical AP50 was 49.1327% on validation (53 chemical annotations). It is retained as history, not compared as a test metric.",
             "The table below re-evaluates both checkpoints with the same untouched test split: imgsz=640, conf=.001, IoU=.7, max_det=300, no TTA, FP32.",
             "The test split contains only four chemical objects: its AP has substantial sampling uncertainty.", "", "## Training configuration", "", "| Parameter | Value |", "|---|---|"]
    configuration = {"Model": f"YOLOv8s / {train.get('starting_checkpoint', 'COCO pretrained yolov8s.pt')}", "Dataset": train["dataset_version"],
                     "Starting checkpoint SHA256": train.get("starting_checkpoint_sha256", initialization.get("sha256", "not captured")),
                     "Requested / completed epochs": f"50 / {train['completed_epochs']}", "Best validation epoch": train["best_epoch"],
                     "Early stop": train["completed_epochs"] < 50, "Runtime": train["environment"], "Focal gamma / alpha": "1.5 / 0.25",
                     "Theoretical cosine endpoint": f"{train['config']['lr0']} × {train['config']['lrf']} = {train['config']['lr0']*train['config']['lrf']}",
                     "Actual final LR": lr[-1],"Classification class weights":train.get("class_weights","all 1"), **train["config"]}
    lines += [f"| {k} | {v} |" for k, v in configuration.items()]
    lines += ["", "Focal implementation replaces only the elementwise BCE callable in v8DetectionLoss. Soft task-aligned targets, sum/target-score normalization, box loss and DFL remain unchanged. Upstream FocalLoss is not used directly because its internal class reduction would change the detection loss scale. Gamma=1.5 and alpha=.25 follow the pinned upstream defaults; conservative online augmentation limits compounding the existing offline augmentations.",
              "Training classification losses use focal loss; upstream EMA validation losses use BCE. Those two loss columns have different scales; validation AP, rather than a train/validation classification-loss ratio, drives checkpoint selection.",
              "", f"Selection: {train['selection']}. No test-driven tuning.", "", "## Controlled experiment comparison (validation)", "",
              "| Run | Initialization | Classification gain | Epochs | Best epoch | Val mAP50 | Val chemical AP50 | Selected |", "|---|---|---:|---:|---:|---:|---:|---|"]
    experiment_notes = []
    for experiment in report.get("all_training_runs", {}).get("runs", [train]):
        name = Path(experiment["run_dir"]).name
        validation = experiment["validation"]
        lines.append(f"| {name} | {experiment.get('starting_checkpoint','yolov8s.pt')} | {experiment['config'].get('cls',.5)} | {experiment['completed_epochs']} | {experiment['best_epoch']} | {validation['overall']['map50']*100:.3f}% | {validation['per_class']['chemical hazard']['ap50']*100:.3f}% | {name == run_name} |")
        experiment_notes.append(f"{name}: {experiment.get('reason','Official requested configuration')}.")
        if experiment.get("resume"):
            experiment_notes.append(f"Infrastructure recovery: {experiment['resume']}. The original optimizer/scaler and requested settings were restored.")
        local_run = TASK / "runtime/runs" / name
        shutil.copy2(local_run / "results.csv", REPORTS / f"{name}_results.csv")
        shutil.copy2(local_run / "args.yaml", REPORTS / f"{name}_args.yaml")
        if (local_run / "results.png").exists(): shutil.copy2(local_run / "results.png", REPORTS / f"{name}_results.png")
    lines += [""] + experiment_notes + ["", "## Held-out test comparison", "", "| Metric | Experiment C | CME-OPT2 |", "|---|---:|---:|"]
    lines += [f"| {key} | {old['overall'][key]*100:.3f}% | {new['overall'][key]*100:.3f}% |" for key in old["overall"]]
    lines += ["", "| Class | C AP50 | New AP50 | Delta (pp) | New P | New R | New AP50-95 | Regression >5pp |", "|---|---:|---:|---:|---:|---:|---:|---|"]
    lines += [f"| {r['class']} | {r['baseline_ap50']*100:.2f} | {r['candidate_ap50']*100:.2f} | {r['ap50_delta']*100:+.2f} | {r['candidate_precision']*100:.2f} | {r['candidate_recall']*100:.2f} | {r['candidate_ap50_95']*100:.2f} | {r['regression_gt_5pp']} |" for r in rows]
    baseline_chem = old["per_class"]["chemical hazard"]["ap50"]
    lines += ["", f"Chemical absolute change: {chemical_delta*100:+.3f} percentage points; relative change: {chemical_delta / baseline_chem * 100 if baseline_chem else float('nan'):.3f}%.",
              f"Chemical AP50 ≥65%: **{'PASS' if report['gates']['chemical_ap50'] else 'FAIL'}** ({new['per_class']['chemical hazard']['ap50']*100:.3f}%).",
              f"Overall mAP50 ≥72%: **{'PASS' if report['gates']['overall_map50'] else 'FAIL'}** ({new['overall']['map50']*100:.3f}%).", "",
              "## Confusion and limitations", ""]
    for name in ("chemical hazard", "smoke"):
        i = train["names"].index(name)
        for label, m in (("Experiment C", old), ("CME-OPT2", new)):
            matrix = np.asarray(m["confusion_matrix"])
            lines.append(f"{label}, {name}: true detections={matrix[i,i]:g}, background misses={matrix[-1,i]:g}, background false positives={matrix[i,-1]:g}. Counts use the validator's confusion threshold and are distinct from AP integration.")
    lines += ["", "Per-class changes and complete confusion matrices are preserved rather than hiding regressions. The four-object chemical test sample and outdoor reference negatives limit any claim of factory deployment generalization. Offline synthetic augmentation and focal loss effects cannot be causally isolated without an ablation experiment.",
              "", "## Deployment and tracking", "", f"Deployment exported: {exported}. Candidate SHA256: `{digest(checkpoint)}`.",
              f"Existing Experiment C backup: `{backup.relative_to(ROOT)}`, SHA256 `{digest(backup)}`; remote copy `Modal industirx-cme-opt2:/baseline.pt`.",
              f"New version: `{VERSION}`. MLflow run: `{report.get('mlflow_run_id')}` in the existing Vision-Driven-Industrial-Safety experiment; artifacts persist on Modal volume `/mlruns`.",
              "Weights/data remain ignored by Git. GPU worker min_containers=0, scaledown_window=600; invocation exits when its work completes.", ""]
    (REPORTS / "CME_OPT2_Evaluation_Report.md").write_text("\n".join(lines), encoding="utf-8")
    status = "pitch_candidate" if exported and report["accepted"] else "deployed_target_shortfall" if exported else "evaluated_target_shortfall"
    metric_values = new["overall"]
    note = json.dumps({"starting_checkpoint": train.get("starting_checkpoint", "yolov8s.pt"), "selected_run":run_name,
                       "metrics_split":"test", "classification_gain":train["config"].get("cls",.5),"baseline_version": "cme1-expanded-12class-v1",
                       "baseline_sha256": digest(backup), "epochs_requested": 50, "epochs_completed": train["completed_epochs"],
                       "best_epoch": train["best_epoch"], "focal_gamma": 1.5, "focal_alpha": .25, "lr0": train["config"]["lr0"], "lrf": .001,
                       "cos_lr": True, "actual_final_lr": lr[-1], "chemical_ap50": new["per_class"]["chemical hazard"]["ap50"],
                       "smoke_ap50": new["per_class"]["smoke"]["ap50"], "checkpoint_sha256": digest(checkpoint),
                       "mlflow_run_id": report.get("mlflow_run_id"), "accepted": report["accepted"]}, separators=(",", ":"))
    best_uri = str(checkpoint.relative_to(ROOT)).replace("\\", "/") + f"; Modal industirx-cme-opt2:/runs/{run_name}/weights/best.pt"
    common = {"sprint": "Sprint 4", "task": "CME-OPT2", "stage": "Model Fine-Tuning", "model_architecture": "YOLOv8s",
              "num_classes": 12, "dataset": "Hazard_Expansion/content_runtime/combined_dataset_augmented_v3",
              "dataset_version": train["dataset_version"], **metric_values, "best_weight_uri": best_uri,
              "last_weight_uri": best_uri.replace("best.pt", "last.pt"), "source_notebook": "Hazard_Expansion/03_train_expanded_model.ipynb", "status": status, "notes": note}
    append(ROOT / "Experiment_Tracking/model_registry.csv", {**common, "model_version": VERSION,
           "purpose": "classification focal and cosine optimization of weak hazard classes", "weight_reference_status": "verified local and Modal best.pt"}, "model_version")
    code_commit = subprocess.run(["git","log","-1","--format=%H","--","CME_OPT2_Model_Fine_Tuning/focal_trainer.py"],
                                 cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip() or "uncommitted execution; source SHA256 recorded in report"
    for contract in report.get("all_training_runs", {}).get("runs", [train]):
        name = Path(contract["run_dir"]).name
        label = contract.get("run_label", "A")
        selected = name == run_name
        version = VERSION if selected else f"cme-opt2-focal-cosine-12class-{label.lower()}"
        values = new["overall"] if selected else contract["validation"]["overall"]
        local = TASK / "runtime/runs" / name / "weights/best.pt"
        uri = local.relative_to(ROOT).as_posix() + f"; Modal industirx-cme-opt2:/runs/{name}/weights/best.pt"
        run_note = json.dumps({"metrics_split":"test" if selected else "val", "selected":selected,
                              "starting_checkpoint":contract.get("starting_checkpoint","yolov8s.pt"),
                              "epochs_requested":50,"epochs_completed":contract["completed_epochs"],"best_epoch":contract["best_epoch"],
                              "classification_gain":contract["config"].get("cls",.5),"optimizer":contract["config"]["optimizer"],"focal_gamma":1.5,"focal_alpha":.25,
                              "lr0":contract["config"]["lr0"],"lrf":.001,"cos_lr":True,"class_weights":contract.get("class_weights","all 1"),"best_sha256":contract["best_sha256"],
                              "mlflow_run_id":report.get("mlflow_run_ids",{}).get(name),"reason":contract.get("reason"),
                              "execution_sources_sha256":contract["execution_sources_sha256"]},separators=(",",":"))
        run_common = {**common, **values,"best_weight_uri":uri,"last_weight_uri":uri.replace("best.pt","last.pt"),
                      "status":status if selected else "not_selected_validation","notes":run_note}
        if not selected:
            append(ROOT / "Experiment_Tracking/model_registry.csv", {**run_common,"model_version":version,
                   "purpose":"controlled focal/cosine experiment retained for validation comparison",
                   "weight_reference_status":"verified local and Modal best.pt"},"model_version")
        append(ROOT / "Experiment_Tracking/experiments.csv", {**run_common,"run_id":f"CMEOPT2-EXP-00{ {'A':1,'B':2,'C':3}[label] }",
               "run_name":f"CME-OPT2-{label}: YOLOv8s focal cosine","experiment_type":"model_finetuning","model_version":version,
               "epochs":contract["completed_epochs"],"batch_size":16,"imgsz":640,"optimizer":contract["config"]["optimizer"],"learning_rate":contract["config"]["lr0"],
               "weight_decay":.0005,"patience":10,"seed":42,"device":"0","environment":f"Modal {contract['environment']['gpu']}",
               "exported_weight_uri":"Backend/best.pt" if selected and exported else "not promoted",
               "source_script":"CME_OPT2_Model_Fine_Tuning/"+{"A":"resume_official.py","B":"controlled_followup.py","C":"targeted_followup.py"}[label],
               "git_commit":code_commit,"tracking_origin":"actual_gpu_training_and_test_evaluation" if selected else "actual_gpu_training_and_validation"},"run_id")
    print("Reports generated, model verified, registries appended. Acceptance:", report["accepted"])


if __name__ == "__main__":
    main()
