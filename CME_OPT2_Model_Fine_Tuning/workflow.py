"""Shared notebook/Modal training and held-out evaluation contract."""
import csv
import hashlib
import json
import platform
import shutil
import sys
import time
import zipfile
from pathlib import Path

import torch
import ultralytics
import yaml
from ultralytics import YOLO
from ultralytics.utils import SETTINGS
from focal_trainer import FocalDetectionTrainer, ClassificationFocalLoss

TASK = Path(__file__).resolve().parent


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def environment():
    return {"python": platform.python_version(), "torch": torch.__version__, "ultralytics": ultralytics.__version__,
            "cuda": torch.version.cuda, "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
            "vram_bytes": torch.cuda.get_device_properties(0).total_memory if torch.cuda.is_available() else 0}


def prepare(work):
    dataset = work / "dataset"
    if not dataset.exists():
        with zipfile.ZipFile(work / "dataset.zip") as archive:
            assert all(not Path(n).is_absolute() and ".." not in Path(n).parts for n in archive.namelist())
            archive.extractall(dataset)
    data = yaml.safe_load((dataset / "data.yaml").read_text())
    names = data["names"]
    names = list(names.values()) if isinstance(names, dict) else names
    assert len(names) == data["nc"] == 12
    assert names[7] == "chemical hazard" and names[10] == "smoke"
    data.update(path=str(dataset.resolve()), train="images/train", val="images/val", test="images/test")
    (dataset / "data.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    manifest = json.loads((work / "input_manifest.json").read_text())
    for rel, expected in manifest["evaluation_files"].items():
        assert digest(dataset / rel) == expected, f"Evaluation split changed: {rel}"
    assert digest(work / "baseline.pt") == manifest["baseline_sha256"]
    print("DATASET", dataset, "chemical=7 smoke=10 evaluation bytes verified", flush=True)
    return dataset / "data.yaml", names


def focal_sanity():
    logits = torch.tensor([-8., 0., 8.], requires_grad=True)
    targets = torch.tensor([0., 1., 1.])
    loss = ClassificationFocalLoss()(logits, targets)
    assert loss.shape == logits.shape and torch.isfinite(loss).all() and loss[1] > loss[0]
    loss.sum().backward()
    assert torch.isfinite(logits.grad).all() and logits.grad[1].abs() > 0
    return {"gamma": 1.5, "alpha": 0.25, "finite_loss": True, "nonzero_gradient": True,
            "elementwise_loss": loss.detach().tolist()}


def metrics(model, data, destination, name, split):
    result = YOLO(str(model)).val(data=str(data), split=split, imgsz=640, batch=16,
                                 device=0 if torch.cuda.is_available() else "cpu", conf=0.001, iou=0.7,
                                 max_det=300, augment=False, half=False, plots=True,
                                 project=str(destination), name=name, exist_ok=False, verbose=False)
    box = result.box
    per_class = {}
    for index, class_id in enumerate(box.ap_class_index):
        p, r, ap50, ap = box.class_result(index)
        per_class[result.names[int(class_id)]] = dict(precision=float(p), recall=float(r), ap50=float(ap50), ap50_95=float(ap))
    assert len(per_class) == 12
    return {"split": split, "checkpoint_sha256": digest(model), "overall": dict(precision=float(box.mp), recall=float(box.mr),
            map50=float(box.map50), map50_95=float(box.map)), "per_class": per_class,
            "confusion_matrix": result.confusion_matrix.matrix.tolist()}


def qualitative(work, data, candidate, destination):
    from PIL import Image, ImageDraw
    dataset = data.parent
    chosen = []
    for class_id, limit in ((7, 100), (10, 3), (6, 2)):
        for label in sorted((dataset / "labels/test").glob("*.txt")):
            if any(int(line.split()[0]) == class_id for line in label.read_text().splitlines() if line.strip()):
                images = list((dataset / "images/test").glob(label.stem + ".*"))
                if images and images[0] not in chosen:
                    chosen.append(images[0])
                    limit -= 1
                    if limit == 0: break
    canvas = Image.new("RGB", (768, len(chosen) * 300), "white")
    draw = ImageDraw.Draw(canvas)
    models = [YOLO(str(work / "baseline.pt")), YOLO(str(candidate))]
    records = []
    for row, image in enumerate(chosen):
        truth = (dataset / "labels/test" / (image.stem + ".txt")).read_text().splitlines()
        gt = [[float(v) for v in line.split()] for line in truth if line.strip()]
        for column, model in enumerate(models):
            result = model.predict(str(image), imgsz=640, device=0, conf=.25, verbose=False)[0]
            panel = Image.fromarray(result.plot()[..., ::-1])
            panel.thumbnail((380, 255))
            canvas.paste(panel, (column * 384, row * 300 + 25))
            draw.text((column * 384 + 4, row * 300 + 2), "Experiment C" if column == 0 else "CME-OPT2", fill="black")
            draw.text((column * 384 + 4, row * 300 + 281), f"GT IDs: {[int(v[0]) for v in gt]}", fill="black")
            records.append({"image": image.name, "model": "baseline" if column == 0 else "candidate",
                            "ground_truth": gt, "predicted_xywhn": result.boxes.xywhn.cpu().tolist(),
                            "predicted_classes": result.boxes.cls.cpu().tolist(), "confidence": result.boxes.conf.cpu().tolist()})
    canvas.save(destination / "qualitative_comparison.png")
    write_json(destination / "qualitative_predictions.json", {"selection": "All chemical test images, first three smoke and first two stain images in filename order; conf=.25; no success filtering", "records": records})


def run(work, mode):
    work = Path(work).resolve()
    SETTINGS.update({"mlflow": False, "wandb": False, "comet": False})
    assert ultralytics.__version__ == "8.4.24", "Install the pinned training environment"
    data, names = prepare(work)
    reports = work / "reports"
    reports.mkdir(exist_ok=True)
    env = environment()
    write_json(reports / "environment.json", env)
    write_json(reports / "focal_sanity.json", focal_sanity())
    if mode in {"smoke", "train"}:
        assert torch.cuda.is_available(), "Official training requires CUDA"
        config = yaml.safe_load((TASK / "config.yaml").read_text())
        name = "smoke" if mode == "smoke" else "cme_opt2_yolov8s_focal_cosine"
        config.update(data=str(data), device=0, project=str(work / "runs"), name=name)
        if mode == "smoke":
            config.update(epochs=1, fraction=0.01, close_mosaic=0, plots=False)
        lr_rows = []
        def record_epoch(trainer):
            values = {"epoch": trainer.epoch + 1, **{f"lr_pg{i}": g["lr"] for i, g in enumerate(trainer.optimizer.param_groups)}}
            if lr_rows and lr_rows[-1]["epoch"] == values["epoch"]:
                return
            lr_rows.append(values)
            with (reports / f"{name}_lr.csv").open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(values)); writer.writeheader(); writer.writerows(lr_rows)
            assert torch.isfinite(trainer.tloss).all(), "Nonfinite training loss"
            print("CME-OPT2 EPOCH", values, "LOSSES", trainer.tloss.tolist(), flush=True)
        model = YOLO(config.pop("model"))
        model.add_callback("on_fit_epoch_end", record_epoch)
        start = time.time()
        model.train(trainer=FocalDetectionTrainer, **config)
        run_dir = work / "runs" / name
        ckpt = torch.load(run_dir / "weights/best.pt", map_location="cpu", weights_only=False)
        history = list(csv.DictReader((run_dir / "results.csv").open()))
        losses = [float(row[k]) for row in history for k in row if "loss" in k]
        assert losses and all(torch.isfinite(torch.tensor(losses)))
        contract = {"dataset_yaml": str(data), "dataset_version": "combined-12class-v3-hardnegative", "names": names,
                    "best": str(run_dir / "weights/best.pt"), "last": str(run_dir / "weights/last.pt"),
                    "run_dir": str(run_dir), "config": config, "focal_gamma": 1.5, "focal_alpha": 0.25,
                    "requested_epochs": config["epochs"], "completed_epochs": len(history),
                    "best_epoch": int(ckpt["train_results"]["epoch"][int(torch.tensor(ckpt["train_results"]["metrics/mAP50-95(B)"]).argmax())]) if "train_results" in ckpt else None,
                    "elapsed_seconds": time.time() - start, "best_sha256": digest(run_dir / "weights/best.pt"), "environment": env}
        contract["execution_sources_sha256"] = {name: digest(TASK / name) for name in ("focal_trainer.py", "workflow.py", "config.yaml", "modal_runner.py")}
        write_json(reports / f"{name}_contract.json", contract)
        if mode == "train":
            # Upstream best.pt selection maximizes validation mAP50-95, never test AP.
            contract["selection"] = "Upstream best validation mAP50-95; no test-driven hyperparameter selection"
            contract["validation"] = metrics(contract["best"], data, reports, "selected_validation", "val")
            write_json(work / "training_contract.json", contract)
        return contract
    if mode == "evaluate":
        contract = json.loads((work / "training_contract.json").read_text())
        assert digest(contract["best"]) == contract["best_sha256"]
        baseline = metrics(work / "baseline.pt", data, reports, "baseline_test", "test")
        candidate = metrics(contract["best"], data, reports, "candidate_test", "test")
        gates = {"chemical_ap50": candidate["per_class"]["chemical hazard"]["ap50"] >= 0.65,
                 "overall_map50": candidate["overall"]["map50"] >= 0.72}
        report = {"baseline": baseline, "candidate": candidate, "gates": gates, "accepted": all(gates.values()),
                  "historical_baseline_chemical_ap50": 0.49132694242889996,
                  "historical_baseline_split": "val (53 chemical annotations); re-evaluated on untouched test for comparison",
                  "selection": contract["selection"], "test_chemical_objects": 4, "training": contract}
        qualitative(work, data, contract["best"], reports)
        write_json(reports / "evaluation.json", report)
        from mlflow_utils import configure_tracking
        mlflow = configure_tracking(work / "mlruns")
        with mlflow.start_run(run_name="CME-OPT2-A: YOLOv8s focal cosine") as tracking_run:
            mlflow.set_tags({"task": "CME-OPT2", "sprint": "Sprint 4", "experiment_type": "model_finetuning",
                             "status": "accepted" if report["accepted"] else "target_shortfall"})
            mlflow.log_params({**contract["config"], "model": "yolov8s.pt", "dataset_version": contract["dataset_version"],
                               "focal_gamma": 1.5, "focal_alpha": 0.25, "best_sha256": contract["best_sha256"],
                               "completed_epochs": contract["completed_epochs"], "best_epoch": contract["best_epoch"]})
            mlflow.log_metrics({**candidate["overall"], "chemical_ap50": candidate["per_class"]["chemical hazard"]["ap50"],
                                "smoke_ap50": candidate["per_class"]["smoke"]["ap50"]})
            lr_history = list(csv.DictReader((reports / "cme_opt2_yolov8s_focal_cosine_lr.csv").open()))
            mlflow.log_param("actual_final_lr", lr_history[-1]["lr_pg0"])
            mlflow.log_artifacts(str(reports), "reports")
            mlflow.log_artifact(str(Path(contract["run_dir"]) / "results.csv"))
            report["mlflow_run_id"] = tracking_run.info.run_id
        write_json(reports / "evaluation.json", report)
        return report
    raise ValueError(mode)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["smoke", "train", "evaluate"])
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.work, args.mode), indent=2))
