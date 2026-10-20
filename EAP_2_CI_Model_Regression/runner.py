"""EAP-2 regression runner: artifact → real /predict contract → golden → quality → latency/memory → report.

python -X utf8 -m EAP_2_CI_Model_Regression.runner [--model PATH] [--skip-quality]

Environment: EAP2_MODEL_PATH overrides the candidate path; EAP2_DATASET_ROOT the
evaluation dataset root. Missing artifacts produce NOT_VERIFIED, never PASS.
"""
from __future__ import annotations

import argparse
import asyncio
import gc
import hashlib
import json
import os
import platform
import statistics
import time
from pathlib import Path

from . import gate

TASK = Path(__file__).resolve().parent
ROOT = TASK.parent
MANIFEST = TASK / "baselines" / "cme-opt2-focal-cosine-12class-v1.json"
GOLDEN = TASK / "golden" / "golden_manifest.json"
POLICY = TASK / "thresholds.json"
REPORTS = ROOT / "reports" / "eap2"
DEFAULT_DATASET = ROOT / "Hazard_Expansion" / "content_runtime" / "combined_dataset_augmented_v3"
FIXTURE = ROOT / "tests" / "assets" / "ife_ui3_fire.png"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def dataset_fingerprint(root: Path, split: str) -> str:
    """SHA256 over sorted (image name, image SHA256, label SHA256) of one split."""
    images = sorted(p for p in (Path(root) / "images" / split).iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
    if not images:
        raise gate.RegressionError(f"No images in {root}/images/{split}")
    digest = hashlib.sha256()
    for image in images:
        label = Path(root) / "labels" / split / (image.stem + ".txt")
        label_sha = gate.sha256_file(label) if label.is_file() else "missing"
        digest.update(f"{image.name}\t{gate.sha256_file(image)}\t{label_sha}\n".encode())
    return digest.hexdigest()


def predict_via_api(model, image: Path) -> dict:
    """Run the real Backend/main.py POST /predict with an injected, already-loaded model."""
    import httpx
    import Backend.main as main
    previous = main.MODEL
    main.MODEL = model
    try:
        async def call():
            transport = httpx.ASGITransport(app=main.api_app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                with image.open("rb") as stream:
                    return await client.post("/predict", files={"file": (image.name, stream, "image/png")})
        response = asyncio.run(call())
    finally:
        main.MODEL = previous
    if response.status_code != 200:
        raise gate.RegressionError(f"/predict returned {response.status_code}: {response.text[:200]}")
    return response.json()


def iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def golden_checks(model, dataset: Path, manifest: gate.BaselineManifest) -> list[gate.Check]:
    """Ground truth comes from human annotations; reference_hit records the accepted baseline's behaviour."""
    if not GOLDEN.is_file():
        return [gate.Check(name="golden", category="quality", status="NOT_VERIFIED", detail="golden manifest missing")]
    spec = json.loads(GOLDEN.read_text(encoding="utf-8"))
    checks = []
    for fixture in spec["fixtures"]:
        path = dataset / "images" / spec["split"] / fixture["image"]
        if not path.is_file() or gate.sha256_file(path) != fixture["image_sha256"]:
            checks.append(gate.Check(name=f"golden:{fixture['id']}", category="quality", status="NOT_VERIFIED",
                                     detail="fixture image missing or hash changed"))
            continue
        result = model.predict(str(path), imgsz=spec["imgsz"], conf=spec["conf"], device="cpu", verbose=False)[0]
        h, w = result.orig_shape
        preds = [(int(c), b) for c, b in zip(result.boxes.cls.tolist(), result.boxes.xyxy.tolist())]
        cx, cy, bw, bh = fixture["box_xywhn"]
        truth = ((cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h)
        hit = any(c == fixture["class_id"] and iou(b, truth) >= spec["iou_match"] for c, b in preds)
        changed = hit != fixture["reference_hit"]
        status = "FAIL" if (changed and not hit) else "PASS"
        detail = (f"{manifest.class_map[fixture['class_id']]} GT {'detected' if hit else 'missed'} at IoU≥{spec['iou_match']}; "
                  f"accepted baseline {'detected' if fixture['reference_hit'] else 'missed'} it")
        if changed and hit:
            detail += " (behaviour changed: new detection)"
        checks.append(gate.Check(name=f"golden:{fixture['id']}", category="quality", status=status, detail=detail,
                                 measured=dict(hit=hit, reference_hit=fixture["reference_hit"])))
    return checks


def latency_memory(model, image: Path, warmup=3, runs=20) -> tuple[gate.Check, gate.Check]:
    import numpy as np
    import psutil
    import cv2
    frame = cv2.imread(str(image))
    process = psutil.Process()
    for _ in range(warmup):
        model.predict(frame, imgsz=640, conf=0.25, device="cpu", verbose=False)
    gc.collect()
    rss_before = process.memory_info().rss
    timings = []
    for _ in range(runs):
        start = time.perf_counter()
        model.predict(frame, imgsz=640, conf=0.25, device="cpu", verbose=False)
        timings.append((time.perf_counter() - start) * 1000)
    gc.collect()
    rss_after = process.memory_info().rss
    lat = dict(runs=runs, warmup=warmup, mean_ms=statistics.fmean(timings), p50_ms=float(np.percentile(timings, 50)),
               p95_ms=float(np.percentile(timings, 95)), max_ms=max(timings), imgsz=640, batch=1, backend="PyTorch CPU",
               note="CI/developer-machine measurement; not a deployment-gateway benchmark; 20 samples make p95 indicative only")
    mem = dict(rss_before_mb=rss_before / 1e6, rss_after_mb=rss_after / 1e6,
               growth_percent=100 * (rss_after - rss_before) / rss_before, runs=runs)
    return (gate.Check(name="latency_cpu", category="performance", status="UNDEFINED_THRESHOLD",
                       detail=f"mean {lat['mean_ms']:.1f} ms, p95 {lat['p95_ms']:.1f} ms; no approved .pt CPU latency SLO", measured=lat),
            gate.Check(name="memory_repeated_inference", category="performance", status="UNDEFINED_THRESHOLD",
                       detail=f"RSS {mem['growth_percent']:+.2f}% over {runs} warmed inferences; no approved gate", measured=mem))


def evaluate_quality(model_path: Path, dataset: Path, manifest: gate.BaselineManifest, scratch: Path) -> dict:
    from ultralytics import YOLO
    import yaml
    data_yaml = scratch / "data.yaml"
    data_yaml.write_text(yaml.safe_dump(dict(path=str(dataset), train="images/train", val="images/val",
                                             test=f"images/{manifest.dataset_split}",
                                             names=[manifest.class_map[i] for i in range(len(manifest.class_map))])), encoding="utf-8")
    s = manifest.evaluation
    result = YOLO(str(model_path)).val(data=str(data_yaml), split="test", imgsz=s.imgsz, batch=s.batch, conf=s.conf,
                                       iou=s.iou, device="cpu", plots=False, project=str(scratch), name="val", verbose=False)
    box = result.box
    per_class = {manifest.class_map[int(c)]: float(box.ap50[i]) for i, c in enumerate(box.ap_class_index)}
    return dict(precision=float(box.mp), recall=float(box.mr), map50=float(box.map50), map50_95=float(box.map),
                per_class_ap50=per_class, settings=s.model_dump())


def run(model_path: Path, dataset: Path, skip_quality: bool, out: Path) -> gate.RegressionReport:
    import tempfile
    from Backend.offline_policy import configure_local_runtime
    configure_local_runtime()
    manifest = gate.load_manifest(MANIFEST)
    policy = gate.ThresholdPolicy.model_validate({k: v for k, v in json.loads(POLICY.read_text()).items() if k in ("version", "thresholds")})
    checks: list[gate.Check] = [gate.verify_artifact(model_path, manifest)]
    metrics, regressions, limitations = {}, [], [
        "No approved model-regression tolerance or CPU latency/memory SLO exists; those checks report UNDEFINED_THRESHOLD.",
        "CI runners do not receive model weights or the dataset (not stored in Git); CI runs code/contract/gate tests only.",
        "Physical network disconnection was not performed; offline checks are automated socket guards only.",
        "CPU evaluation may differ slightly from the GPU-measured baseline; deltas are reported, not hidden.",
    ]
    model = None
    if checks[0].status != "NOT_VERIFIED":
        from ultralytics import YOLO
        started = time.perf_counter()
        model = YOLO(str(model_path))
        load_ms = (time.perf_counter() - started) * 1000
        checks.append(gate.compare_class_map(model.names, manifest))
        checks[-1].measured = dict(load_ms=load_ms)
        try:
            from PIL import Image
            with Image.open(FIXTURE) as image:
                width, height = image.size
            payload = predict_via_api(model, FIXTURE)
            response = gate.validate_response(payload, manifest.class_map, width, height)
            checks.append(gate.Check(name="predict_api_contract", category="inference", status="PASS",
                                     detail=f"real /predict returned {len(response.detections)} contract-valid detections",
                                     measured=dict(classes=sorted({d.class_name for d in response.detections}))))
            again = predict_via_api(model, FIXTURE)
            stable = len(again["detections"]) == len(payload["detections"]) and all(
                abs(a["confidence"] - b["confidence"]) <= 1e-4 for a, b in zip(again["detections"], payload["detections"]))
            checks.append(gate.Check(name="repeat_inference_stability", category="inference",
                                     status="PASS" if stable else "FAIL", detail="identical input re-run within 1e-4 confidence"))
        except (gate.RegressionError, ValueError) as exc:
            checks.append(gate.Check(name="predict_api_contract", category="inference", status="FAIL", detail=str(exc)[:500]))
        checks.extend(latency_memory(model, FIXTURE))
    else:
        checks.append(gate.Check(name="class_map", category="artifact", status="NOT_VERIFIED", detail="model artifact unavailable"))
    fingerprint = None
    if model is None or not (dataset / "images" / manifest.dataset_split).is_dir():
        checks.append(gate.Check(name="quality_regression", category="quality", status="NOT_VERIFIED",
                                 detail=f"model or evaluation dataset unavailable ({dataset})"))
    else:
        checks.extend(golden_checks(model, dataset, manifest))
        fingerprint = dataset_fingerprint(dataset, manifest.dataset_split)
        if skip_quality:
            checks.append(gate.Check(name="quality_regression", category="quality", status="NOT_VERIFIED", detail="skipped by --skip-quality"))
        else:
            with tempfile.TemporaryDirectory(prefix="eap2-") as scratch:
                started = time.perf_counter()
                candidate = evaluate_quality(model_path, dataset, manifest, Path(scratch))
                seconds = time.perf_counter() - started
            quality, regressions, metrics = gate.compare_metrics(candidate, manifest, policy, candidate["settings"], fingerprint)
            metrics["evaluation_seconds"] = seconds
            metrics["baseline"] = manifest.metrics.model_dump()
            checks.extend(quality)
    statuses = [c.status for c in checks]
    code_status = "PASS"
    versions = {}
    for name in ("torch", "ultralytics", "pydantic"):
        try:
            versions[name] = __import__(name).__version__
        except ImportError:
            versions[name] = None
    report = gate.RegressionReport(
        status=gate.overall(statuses), code_status=code_status,
        model_release_status=gate.overall([c.status for c in checks if c.category in ("artifact", "inference", "quality", "performance")]),
        model_id=manifest.model_version if checks[0].status == "PASS" else None, model_version=manifest.model_version if checks[0].status == "PASS" else None,
        model_sha256=(checks[0].measured or {}).get("sha256"), baseline_id=manifest.baseline_id, dataset_fingerprint=fingerprint,
        checks=checks, metrics=metrics, regressions=regressions,
        thresholds=json.loads(POLICY.read_text()), limitations=limitations,
        environment=dict(python=platform.python_version(), platform=platform.platform(), **versions, device="cpu", model_path=str(model_path.relative_to(ROOT)) if model_path.is_relative_to(ROOT) else model_path.name))
    gate.write_report(report, out)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, default=Path(os.getenv("EAP2_MODEL_PATH", ROOT / "Backend" / "best.pt")))
    parser.add_argument("--dataset", type=Path, default=Path(os.getenv("EAP2_DATASET_ROOT", DEFAULT_DATASET)))
    parser.add_argument("--skip-quality", action="store_true")
    parser.add_argument("--out", type=Path, default=REPORTS / "regression_report.json")
    args = parser.parse_args()
    report = run(args.model.resolve(), args.dataset, args.skip_quality, args.out)
    for check in report.checks:
        print(f"{check.status:20s} {check.name:40s} {check.detail}")
    print(f"OVERALL {report.status} | code {report.code_status} | model release {report.model_release_status}")
    raise SystemExit(1 if report.status == "FAIL" else 0)


if __name__ == "__main__":
    main()
