"""Read-only audit of real training, evaluation, lineage and deployment evidence."""
import csv
import json
import math
import sys
from pathlib import Path
from workflow import digest, write_json

ROOT = Path(__file__).resolve().parent.parent
TASK = ROOT / "CME_OPT2_Model_Fine_Tuning"


def main():
    report = json.loads((TASK / "reports/evaluation.json").read_text())
    train = report["training"]
    official=next(c for c in report["all_training_runs"]["runs"] if c.get("run_label","A")=="A")
    candidate = report["candidate"]
    checks = {}
    checks["official_requested_configuration"] = all(official["config"].get(k) == v for k, v in {
        "epochs": 50, "patience": 10, "imgsz": 640, "batch": 16, "optimizer": "SGD",
        "lr0": .01, "lrf": .001, "cos_lr": True, "seed": 42, "amp": True}.items())
    checks["genuine_training"] = (1 <= train["completed_epochs"] <= 50 and 1 <= train["best_epoch"] <= train["completed_epochs"]
                                  and train["environment"]["gpu"] is not None)
    checks["controlled_variants_documented"] = len(report["all_training_runs"]["runs"]) <= 3 and all(c.get("reason") for c in report["all_training_runs"]["runs"])
    checks["classification_focal"] = train["focal_gamma"] == 1.5 and train["focal_alpha"] == .25
    checks["test_comparison"] = report["baseline"]["split"] == candidate["split"] == "test"
    checks["all_12_classes"] = len(candidate["per_class"]) == len(report["baseline"]["per_class"]) == 12
    checks["mean_ap_consistent"] = math.isclose(sum(v["ap50"] for v in candidate["per_class"].values()) / 12,
                                                candidate["overall"]["map50"], abs_tol=1e-10)
    weights = TASK / "runtime/runs" / Path(train["run_dir"]).name / "weights"
    checks["checkpoint_identity"] = digest(weights / "best.pt") == candidate["checkpoint_sha256"] == train["best_sha256"]
    checks["last_checkpoint_retained"] = (weights / "last.pt").is_file()
    checks["baseline_retained"] = digest(TASK / "runtime/baseline.pt") == report["baseline"]["checkpoint_sha256"]
    checks["execution_sources"] = all(digest(TASK / name) == expected
        for contract in report["all_training_runs"]["runs"]
        for name, expected in contract["execution_sources_sha256"].items())
    manifest = json.loads((TASK / "runtime/input_manifest.json").read_text())
    dataset = ROOT / "Hazard_Expansion/content_runtime/combined_dataset_augmented_v3"
    original = ROOT / "Hazard_Expansion/content_runtime/combined_dataset"
    checks["evaluation_bytes_unchanged"] = all(digest(dataset / rel) == digest(original / rel) == expected
                                               for rel, expected in manifest["evaluation_files"].items())
    deployment = json.loads((TASK / "reports/deployment_verification.json").read_text())
    checks["backend_smoke"] = deployment["candidate_load"] and deployment["inference"] and len(deployment["classes"]) == 12
    checks["deployment_policy"] = deployment["exported"] and bool(train.get("selection"))
    checks["deployed_hash"] = digest(ROOT / "Backend/best.pt") == train["best_sha256"]
    checks["mlflow_recorded"] = bool(report.get("mlflow_run_id"))
    with (ROOT / "Experiment_Tracking/model_registry.csv").open(encoding="utf-8", newline="") as stream:
        model = next((r for r in csv.DictReader(stream) if r["model_version"] == "cme-opt2-focal-cosine-12class-v1"), None)
    checks["model_registry"] = bool(model and math.isclose(float(model["map50"]), candidate["overall"]["map50"], abs_tol=1e-10))
    with (ROOT / "Experiment_Tracking/experiments.csv").open(encoding="utf-8", newline="") as stream:
        experiment = next((r for r in csv.DictReader(stream) if r["model_version"] == "cme-opt2-focal-cosine-12class-v1"), None)
    checks["experiment_registry"] = bool(experiment and experiment["experiment_type"] == "model_finetuning" and experiment["task"] == "CME-OPT2")
    checks["measured_plots"] = all((TASK / "reports" / name).is_file() for name in (
        "class_comparison.png", "learning_rate.png", "candidate_test/confusion_matrix.png",
        "candidate_test/BoxPR_curve.png", "qualitative_comparison.png"))
    checks["chemical_target"] = candidate["per_class"]["chemical hazard"]["ap50"] >= .65
    checks["overall_target"] = candidate["overall"]["map50"] >= .72
    actual = all(checks.values())
    write_json(TASK / "reports/acceptance_audit.json", {"accepted": actual, "checks": checks,
               "chemical_ap50": candidate["per_class"]["chemical hazard"]["ap50"], "overall_map50": candidate["overall"]["map50"]})
    for key, passed in checks.items(): print(f"{key}: {'PASS' if passed else 'FAIL'}")
    print("CME-OPT2 acceptance:", "PASS" if actual else "FAIL")
    return 0 if actual else 1


if __name__ == "__main__":
    sys.exit(main())
