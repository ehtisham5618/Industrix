"""Identical-settings detector evaluation for baseline and candidate across lighting domains."""
import math
from collections import Counter
from pathlib import Path
import yaml

try:
    from .dataset_tools import DatasetError, IMAGE_SUFFIXES, label_for, load_names, parse_label_file
except ImportError:
    from dataset_tools import DatasetError, IMAGE_SUFFIXES, label_for, load_names, parse_label_file

REQUIRED_METRICS = ("precision", "recall", "map50", "map50_95")


def split_counts(data_yaml, split):
    data = yaml.safe_load(Path(data_yaml).read_text(encoding="utf-8"))
    names = load_names(data_yaml)
    folder = Path(data["path"]) / data[split]
    images = [p for p in folder.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES]
    objects = Counter(b[0] for p in images for b in parse_label_file(label_for(p), len(names))[0])
    return dict(images=len(images), objects=sum(objects.values()),
                class_objects={names[c]: objects.get(c, 0) for c in range(len(names))})


def check_class_map(model_names, data_names):
    model_names = {int(k): v for k, v in dict(model_names).items()}
    if model_names != data_names:
        raise DatasetError(f"Checkpoint class map {model_names} does not match dataset {data_names}")


def evaluate(model_path, data_yaml, split, settings, project, name):
    """Run Ultralytics validation with fixed settings and return machine-readable metrics."""
    from ultralytics import YOLO
    if not Path(model_path).is_file():
        raise DatasetError(f"Checkpoint not found: {model_path}")
    names = load_names(data_yaml)
    model = YOLO(str(model_path))
    check_class_map(model.names, names)
    result = model.val(data=str(data_yaml), split=split, imgsz=settings["imgsz"], batch=settings["batch"],
                       conf=settings["conf"], iou=settings["iou"], plots=True, project=str(project), name=name,
                       exist_ok=False, verbose=False)
    box = result.box
    per_class = {}
    for position, cls in enumerate(box.ap_class_index):
        per_class[names[int(cls)]] = dict(ap50=float(box.ap50[position]), ap50_95=float(box.ap[position]),
                                           precision=float(box.p[position]), recall=float(box.r[position]))
    metrics = dict(precision=float(box.mp), recall=float(box.mr), map50=float(box.map50), map50_95=float(box.map))
    return dict(split=split, data=str(data_yaml), settings=dict(settings), metric_unit="fraction_0_to_1", **metrics,
                per_class=per_class, counts=split_counts(data_yaml, split),
                confusion_matrix=result.confusion_matrix.matrix.astype(int).tolist(),
                confusion_labels=[names[i] for i in range(len(names))] + ["background"],
                output_dir=str(result.save_dir))


def validate_report(report):
    """Reject reports with missing, non-finite or out-of-range required metrics."""
    for key in REQUIRED_METRICS:
        value = report.get(key)
        if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError(f"Invalid or missing metric {key!r}: {value!r}")
    if report.get("counts", {}).get("images", 0) <= 0:
        raise ValueError("Evaluation report has no images")
    for cls, values in report.get("per_class", {}).items():
        for key in ("ap50", "ap50_95"):
            if not 0 <= values[key] <= 1:
                raise ValueError(f"Invalid per-class {key} for {cls}")
    return True


def compare(baseline, candidate):
    """Absolute candidate-minus-baseline deltas (fractions) for overall and per-class metrics."""
    if baseline["settings"] != candidate["settings"] or baseline["counts"] != candidate["counts"]:
        raise ValueError("Baseline and candidate were not evaluated with equivalent settings/data")
    overall = {k: candidate[k] - baseline[k] for k in REQUIRED_METRICS}
    classes = sorted(set(baseline["per_class"]) | set(candidate["per_class"]))
    per_class = {c: dict(baseline_ap50=baseline["per_class"].get(c, {}).get("ap50"),
                         candidate_ap50=candidate["per_class"].get(c, {}).get("ap50"),
                         delta_ap50=(candidate["per_class"][c]["ap50"] - baseline["per_class"][c]["ap50"])
                         if c in baseline["per_class"] and c in candidate["per_class"] else None)
                 for c in classes}
    return dict(overall=overall, per_class=per_class)
