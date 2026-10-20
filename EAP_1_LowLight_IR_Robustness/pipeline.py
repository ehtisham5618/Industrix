"""EAP-1 end-to-end worker: verify inputs, build robustness data, baseline eval,
fine-tune from the verified production checkpoint, candidate eval.

Selection uses validation only (Ultralytics best.pt fitness on original val plus
fixed synthetic val domains). Test domains are evaluated once, after training.
"""
import argparse
import json
import platform
import shutil
import sys
import time
import traceback
import zipfile
from datetime import datetime, timezone
from pathlib import Path
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dataset_tools as tools  # noqa: E402
import evaluate as ev  # noqa: E402


def now():
    return datetime.now(timezone.utc).isoformat()


class Status:
    def __init__(self, path):
        self.path, self.data = path, dict(task="EAP-1", stages={}, training_status="not_started")

    def stage(self, name, **values):
        self.data["stages"][name] = dict(at=now(), **values)
        self.save()

    def save(self):
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")


def evaluate_all(model, domains, settings, project, label, status):
    results = {}
    for domain, data_yaml in domains.items():
        for split in ("test",) if domain != "standard_val" else ("val",):
            report = ev.evaluate(model, data_yaml, split, settings, project, f"{label}_{domain}_{split}")
            ev.validate_report(report)
            results[domain] = report
            status.stage(f"{label}_{domain}", map50=report["map50"], map50_95=report["map50_95"])
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", required=True)
    parser.add_argument("--source-volume", required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--scratch", default="/tmp/eap1")
    args = parser.parse_args()
    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    work, scratch = Path(args.work), Path(args.scratch)
    reports = work / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    status = Status(reports / "status.json")
    import torch, ultralytics, cv2, numpy
    status.data["environment"] = dict(python=platform.python_version(), torch=torch.__version__,
                                      ultralytics=ultralytics.__version__, opencv=cv2.__version__, numpy=numpy.__version__,
                                      cuda=torch.version.cuda, gpu=torch.cuda.get_device_name() if torch.cuda.is_available() else None)
    status.stage("start")

    baseline_sha = tools.sha256_file(args.baseline)
    if baseline_sha != config["source_checkpoint"]["sha256"]:
        raise tools.DatasetError(f"Baseline checkpoint hash mismatch: {baseline_sha}")
    archive = Path(args.source_volume) / config["dataset"]["modal_zip"]
    scratch.mkdir(parents=True, exist_ok=True)
    local_zip = scratch / "dataset.zip"
    shutil.copyfile(archive, local_zip)
    zip_sha = tools.sha256_file(local_zip)
    if zip_sha != config["dataset"]["zip_sha256"]:
        raise tools.DatasetError(f"Dataset archive hash mismatch: {zip_sha}")
    source = scratch / "source"
    with zipfile.ZipFile(local_zip) as zipped:
        assert all(not Path(n).is_absolute() and ".." not in Path(n).parts for n in zipped.namelist())
        zipped.extractall(source)
    local_zip.unlink()
    names = tools.load_names(source / "data.yaml")
    tools.write_yaml(source / "data.yaml", dict(path=str(source), train="images/train", val="images/val",
                                                 test="images/test", names=names))
    status.stage("inputs_verified", baseline_sha256=baseline_sha, dataset_zip_sha256=zip_sha, class_names=names)

    audit = tools.audit_dataset(source, workers=8, near_duplicates=False)
    (reports / "source_audit_remote.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    if audit["invalid_images"] or audit["invalid_labels"]:
        raise tools.DatasetError("Source dataset failed validation; see source_audit_remote.json")
    robust = scratch / "eap1_dataset_v1"
    manifest = tools.build_robust_dataset(source, robust, config, workers=8)
    natural = tools.build_natural_dark(source, scratch / "natural_dark", config["evaluation"]["natural_dark_luma_max"])
    manifest["natural_dark"] = dict(threshold=config["evaluation"]["natural_dark_luma_max"], images=natural)
    (reports / "dataset_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    robust_audit = tools.audit_dataset(robust, workers=8, near_duplicates=False)
    (reports / "robust_audit_remote.json").write_text(json.dumps(robust_audit, indent=2), encoding="utf-8")
    if robust_audit["invalid_images"] or robust_audit["invalid_labels"]:
        raise tools.DatasetError("Built robustness dataset failed validation")
    status.stage("dataset_built", train_total=manifest["train_total"], train_augmented=manifest["train_augmented"])

    settings = {k: config["evaluation"][k] for k in ("imgsz", "batch", "conf", "iou")}
    domains = dict(standard_val=source / "data.yaml", standard=source / "data.yaml")
    if natural["test"]:
        domains["natural_dark"] = scratch / "natural_dark" / "data.yaml"
    for domain in ("synthetic_lowlight", "synthetic_very_dark", "synthetic_cctv", "synthetic_ir_style"):
        domains[domain] = robust / "domains" / domain / "data.yaml"
    evals = work / "evaluations"
    baseline_results = evaluate_all(args.baseline, domains, settings, evals, "baseline", status)
    (reports / "baseline_metrics.json").write_text(json.dumps(baseline_results, indent=2), encoding="utf-8")

    from focal_trainer import FocalDetectionTrainer
    train_cfg = dict(config["training"])
    overrides = dict(model=args.baseline, data=str(robust / "data.yaml"), project=str(work / "runs"),
                     name="eap1_lowlight_v1", device=0, **train_cfg)
    status.data.update(training_status="running", training_overrides=overrides, training_start=now())
    status.save()
    started = time.monotonic()
    try:
        trainer = FocalDetectionTrainer(overrides=overrides)
        trainer.train()
    except BaseException:
        status.data.update(training_status="interrupted_or_failed", training_error=traceback.format_exc(),
                           training_end=now(), training_seconds=time.monotonic() - started)
        status.save()
        raise
    run = Path(trainer.save_dir)
    rows = (run / "results.csv").read_text().strip().splitlines()[1:]
    best = run / "weights" / "best.pt"
    status.data.update(training_status="completed", training_end=now(), training_seconds=time.monotonic() - started,
                       epochs_completed=len(rows), epochs_requested=train_cfg["epochs"],
                       early_stopped=len(rows) < train_cfg["epochs"], run_dir=str(run),
                       best_sha256=tools.sha256_file(best), last_sha256=tools.sha256_file(run / "weights" / "last.pt"))
    status.save()

    candidate_results = evaluate_all(best, domains, settings, evals, "candidate", status)
    (reports / "candidate_metrics.json").write_text(json.dumps(candidate_results, indent=2), encoding="utf-8")
    comparison = {d: ev.compare(baseline_results[d], candidate_results[d]) for d in baseline_results}
    (reports / "comparison.json").write_text(json.dumps(comparison, indent=2), encoding="utf-8")
    status.stage("complete")


if __name__ == "__main__":
    main()
