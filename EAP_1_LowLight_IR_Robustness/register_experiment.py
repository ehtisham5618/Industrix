"""Append the measured EAP-1 run to the existing CSV registries (idempotent, no invented values)."""
import csv
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRACKING = ROOT / "Experiment_Tracking"
SUMMARY = ROOT / "reports" / "eap1" / "eap1_robustness_summary.json"
MODEL_VERSION = "eap1-lowlight-cctv-12class-v1"


def append(path, key, row):
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames
        if any(existing[key] == row[key] for existing in reader):
            return False
    with path.open("a", encoding="utf-8", newline="") as handle:
        csv.DictWriter(handle, fieldnames=fields).writerow({f: row.get(f, "") for f in fields})
    return True


def main():
    s = json.loads(SUMMARY.read_text(encoding="utf-8"))
    t, test = s["training"], s["evaluation"]["candidate"]["standard"]
    if t["status"] != "completed":
        raise SystemExit("Training not completed; refusing to register a candidate model")
    o = t["overrides"]
    notes = json.dumps(dict(
        starting_checkpoint=s["source_checkpoint"]["model_version"], baseline_sha256=s["source_checkpoint"]["sha256"],
        checkpoint_sha256=t["best_sha256"], metrics_split="test (standard domain)", selection="validation fitness on original+synthetic val",
        epochs_requested=t["epochs_requested"], epochs_completed=t["epochs_completed"],
        domain_delta_map50_95={d: v["overall"]["map50_95"] for d, v in s["evaluation"]["comparison"].items()},
        genuine_ir_evaluated=False, exported=False, accepted=False, summary="reports/eap1/eap1_robustness_summary.json"),
        separators=(",", ":"))
    weights = s["candidate"]["path"] + "; Modal " + s["candidate"]["modal"].replace(":/", ":/")
    append(TRACKING / "model_registry.csv", "model_version", dict(
        model_version=MODEL_VERSION, sprint="Sprint 3", task="EAP-1", stage="Low-light/CCTV robustness fine-tuning",
        model_architecture="YOLOv8s", num_classes=12, purpose="low-light, CCTV degradation and synthetic IR-style robustness",
        dataset="combined-12class-v3-hardnegative + EAP-1 training-only degradations", dataset_version="eap1-robust-v1",
        precision=test["precision"], recall=test["recall"], map50=test["map50"], map50_95=test["map50_95"],
        best_weight_uri=weights, last_weight_uri="industirx-eap1:/runs/eap1_lowlight_v1/weights/last.pt",
        weight_reference_status="verified local and Modal best.pt" if t["local_candidate_sha256_matches"] else "Modal only",
        source_notebook="", status="candidate_not_deployment_validated", notes=notes))
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    env = t["environment"] or {}
    append(TRACKING / "experiments.csv", "run_id", dict(
        run_id="EAP1-EXP-001", run_name="EAP-1 low-light/CCTV robustness fine-tune", sprint="Sprint 3", task="EAP-1",
        stage="Robustness fine-tuning", experiment_type="model_finetuning", model_version=MODEL_VERSION,
        model_architecture="YOLOv8s", dataset="combined-12class-v3-hardnegative", dataset_version="eap1-robust-v1",
        num_classes=12, epochs=t["epochs_completed"], batch_size=o["batch"], imgsz=o["imgsz"], optimizer=o["optimizer"],
        learning_rate=o["lr0"], weight_decay=o["weight_decay"], patience=o["patience"], seed=o["seed"],
        device=env.get("gpu", ""), environment=f"Modal / Python{env.get('python')} / torch{env.get('torch')} / ultralytics{env.get('ultralytics')}",
        precision=test["precision"], recall=test["recall"], map50=test["map50"], map50_95=test["map50_95"],
        best_weight_uri=weights, last_weight_uri="industirx-eap1:/runs/eap1_lowlight_v1/weights/last.pt",
        source_script="EAP_1_LowLight_IR_Robustness/pipeline.py", git_commit=commit,
        status="implementation_verified_performance_threshold_undefined", tracking_origin="measured_modal_run",
        confidence_config="EAP_1_LowLight_IR_Robustness/configs/eap1_lowlight.yaml", notes=notes))
    print("Registered", MODEL_VERSION)


if __name__ == "__main__":
    main()
