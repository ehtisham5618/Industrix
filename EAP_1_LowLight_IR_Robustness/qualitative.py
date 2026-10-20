"""Side-by-side baseline vs candidate predictions on real-dark and synthetic very-dark test images (CPU, offline)."""
import json
import sys
from pathlib import Path
import cv2
import numpy as np
import yaml

TASK = Path(__file__).resolve().parent
ROOT = TASK.parent
sys.path.insert(0, str(TASK))
import dataset_tools as tools  # noqa: E402
import degradations  # noqa: E402

REPORTS = ROOT / "reports" / "eap1"
CANDIDATE = TASK / "runtime" / "eap1_lowlight_v1" / "best.pt"


def draw(image, boxes, names, color):
    out = image.copy()
    for (x1, y1, x2, y2), cls, conf in boxes:
        cv2.rectangle(out, (int(x1), int(y1)), (int(x2), int(y2)), color, max(2, out.shape[1] // 250))
        cv2.putText(out, f"{names[cls]} {conf:.2f}", (int(x1), max(18, int(y1) - 4)), cv2.FONT_HERSHEY_SIMPLEX,
                    max(0.5, out.shape[1] / 1000), color, 2)
    return cv2.resize(out, (360, 270))


def predict(model, image, conf):
    r = model.predict(image, imgsz=640, conf=conf, device="cpu", verbose=False)[0]
    return [(b.tolist(), int(c), float(s)) for b, c, s in zip(r.boxes.xyxy, r.boxes.cls, r.boxes.conf)]


def main(count=3, conf=0.25):
    from ultralytics import YOLO
    config = yaml.safe_load((TASK / "configs" / "eap1_lowlight.yaml").read_text(encoding="utf-8"))
    source = ROOT / config["dataset"]["local_root"]
    names = tools.load_names(source / "data.yaml")
    manifest = json.loads((REPORTS / "remote" / "dataset_manifest.json").read_text(encoding="utf-8"))
    dark = manifest["natural_dark"]["images"]["test"]
    test = sorted(p.name for p in (source / "images" / "test").iterdir())
    picks = [("natural_dark", n) for n in dark[:count]] + \
            [("synthetic_very_dark", test[i]) for i in np.linspace(0, len(test) - 1, count).astype(int)]
    baseline, candidate = YOLO(str(ROOT / "Backend/best.pt")), YOLO(str(CANDIDATE))
    rows, records = [], []
    for domain, name in picks:
        image = cv2.imread(str(source / "images" / "test" / name))
        if domain != "natural_dark":
            image = degradations.apply(image, domain, degradations.rng_for(config["seed"], "qualitative", name))[0]
        gt, _ = tools.parse_label_file(tools.label_for(source / "images" / "test" / name), len(names))
        h, w = image.shape[:2]
        truth = [(((cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h), c, 1.0) for c, cx, cy, bw, bh in gt]
        b, c = predict(baseline, image, conf), predict(candidate, image, conf)
        tiles = [draw(image, truth, names, (0, 255, 0)), draw(image, b, names, (0, 165, 255)), draw(image, c, names, (255, 120, 0))]
        for tile, label in zip(tiles, ("ground truth", "baseline", "candidate")):
            cv2.putText(tile, f"{domain}: {label}", (5, 262), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 2)
        rows.append(np.hstack(tiles))
        records.append(dict(domain=domain, image=name, ground_truth=[names[t[1]] for t in truth],
                            baseline=[(names[k], round(s, 3)) for _, k, s in b], candidate=[(names[k], round(s, 3)) for _, k, s in c]))
    cv2.imwrite(str(REPORTS / "qualitative_baseline_vs_candidate.png"), np.vstack(rows))
    (REPORTS / "qualitative_examples.json").write_text(json.dumps(dict(conf=conf, device="cpu", examples=records), indent=2), encoding="utf-8")
    for r in records:
        print(r)


if __name__ == "__main__":
    main()
