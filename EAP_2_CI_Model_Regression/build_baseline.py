"""Explicit, reviewer-run baseline creation. Never invoked by tests or CI.

Metrics come from the recorded EAP-1 baseline evaluation of the accepted
production checkpoint (reports/eap1/remote/baseline_metrics.json); golden ground
truth comes from human annotations. Refuses to overwrite an existing baseline.
"""
import argparse
import json
from pathlib import Path

from . import gate
from .runner import DEFAULT_DATASET, GOLDEN, MANIFEST, ROOT, dataset_fingerprint, iou

SOURCE = ROOT / "reports" / "eap1" / "remote"
CHECKPOINT = ROOT / "Backend" / "best.pt"


def build_manifest(dataset: Path):
    measured = json.loads((SOURCE / "baseline_metrics.json").read_text(encoding="utf-8"))["standard"]
    status = json.loads((SOURCE / "status.json").read_text(encoding="utf-8"))
    stages = status["stages"]["inputs_verified"]
    names = {int(k): v for k, v in stages["class_names"].items()}
    sha = gate.sha256_file(CHECKPOINT)
    if sha != stages["baseline_sha256"]:
        raise gate.RegressionError("Backend/best.pt is not the checkpoint the recorded baseline measured")
    manifest = gate.BaselineManifest(
        baseline_id="eap2-baseline-cme-opt2-v1", model_version="cme-opt2-focal-cosine-12class-v1", architecture="YOLOv8s",
        backend="Ultralytics PyTorch", artifact_path="Backend/best.pt", artifact_sha256=sha, class_map=names,
        dataset_id="combined-12class-v3-hardnegative", dataset_split="test", dataset_archive_sha256=stages["dataset_zip_sha256"],
        dataset_fingerprint=dataset_fingerprint(dataset, "test"), dataset_counts=measured["counts"],
        evaluation=measured["settings"], inference_conf=0.25,
        metrics={k: measured[k] for k in gate.METRICS},
        per_class_ap50={k: v["ap50"] for k, v in measured["per_class"].items()},
        source="reports/eap1/remote/baseline_metrics.json (EAP-1 measured run, Modal NVIDIA A10, 2026-10-20)",
        measured_environment=status["environment"],
        notes=["Metrics were measured on GPU; local CPU re-evaluation may differ by small amounts.",
               "Matches the historical CME-OPT2 test mAP50 0.78156 within 0.0002."])
    return manifest


def build_golden(dataset: Path, manifest: gate.BaselineManifest, split="test", imgsz=640, conf=0.25, iou_match=0.5):
    from ultralytics import YOLO
    model = YOLO(str(CHECKPOINT))
    fixtures = []
    images = sorted(p for p in (dataset / "images" / split).iterdir())
    for class_id, name in manifest.class_map.items():
        for path in images:
            rows = [r.split() for r in (dataset / "labels" / split / (path.stem + ".txt")).read_text().splitlines() if r.strip()]
            box = next((list(map(float, r[1:])) for r in rows if int(r[0]) == class_id), None)
            if box is None:
                continue
            result = model.predict(str(path), imgsz=imgsz, conf=conf, device="cpu", verbose=False)[0]
            h, w = result.orig_shape
            truth = ((box[0] - box[2] / 2) * w, (box[1] - box[3] / 2) * h, (box[0] + box[2] / 2) * w, (box[1] + box[3] / 2) * h)
            hit = any(int(c) == class_id and iou(b, truth) >= iou_match
                      for c, b in zip(result.boxes.cls.tolist(), result.boxes.xyxy.tolist()))
            fixtures.append(dict(id=f"{class_id:02d}-{name.replace(' ', '_')}", image=path.name, image_sha256=gate.sha256_file(path),
                                 class_id=class_id, box_xywhn=box, reference_hit=hit,
                                 provenance="combined-12class-v3-hardnegative test split; licences per CME-1/CME-OPT1 attributions; internal evaluation use"))
            break
    return dict(version="eap2-golden-v1", split=split, imgsz=imgsz, conf=conf, iou_match=iou_match,
                reference_model=manifest.model_version, reference_sha256=manifest.artifact_sha256,
                selection="first test image (sorted by name) containing each class; first annotated box of that class",
                expected_source="human annotation labels; reference_hit = accepted baseline behaviour, not candidate output",
                fixtures=fixtures)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    args = parser.parse_args()
    if MANIFEST.exists() or GOLDEN.exists():
        raise SystemExit("Baseline already exists; baselines are reviewed and replaced deliberately, never regenerated in place")
    manifest = build_manifest(args.dataset)
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest.model_dump(), indent=2), encoding="utf-8")
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN.write_text(json.dumps(build_golden(args.dataset, manifest), indent=2), encoding="utf-8")
    print("Wrote", MANIFEST.relative_to(ROOT), "and", GOLDEN.relative_to(ROOT))


if __name__ == "__main__":
    main()
