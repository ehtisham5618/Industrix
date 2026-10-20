"""Local, offline dataset audit + qualitative contact sheet for EAP-1 (no training)."""
import json
import sys
import time
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


def contact_sheet(source, seed, output, count=4):
    """Original vs each degradation with unchanged boxes drawn, for visual label-validity inspection."""
    names = tools.load_names(source / "data.yaml")
    images = sorted((source / "images" / "test").iterdir())
    picks = [images[i] for i in np.linspace(0, len(images) - 1, count).astype(int)]
    profiles = ("original",) + degradations.EVAL_DOMAINS + ("uneven_illumination",)
    rows = []
    for path in picks:
        image = cv2.imread(str(path))
        boxes, _ = tools.parse_label_file(tools.label_for(path), len(names))
        tiles = []
        for profile in profiles:
            out = image.copy() if profile == "original" else degradations.apply(image, profile, degradations.rng_for(seed, "sheet", path.name))[0]
            h, w = out.shape[:2]
            for cls, cx, cy, bw, bh in boxes:
                x1, y1, x2, y2 = int((cx - bw / 2) * w), int((cy - bh / 2) * h), int((cx + bw / 2) * w), int((cy + bh / 2) * h)
                cv2.rectangle(out, (x1, y1), (x2, y2), (0, 255, 0), max(2, w // 200))
                cv2.putText(out, names[cls], (x1, max(20, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, max(0.6, w / 900), (0, 255, 0), 2)
            out = cv2.resize(out, (320, int(320 * h / w)))
            out = cv2.resize(out, (320, 240))
            cv2.putText(out, profile, (5, 232), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)
            tiles.append(out)
        rows.append(np.hstack(tiles))
    cv2.imwrite(str(output), np.vstack(rows))
    return dict(images=[p.name for p in picks], profiles=list(profiles))


def main():
    config = yaml.safe_load((TASK / "configs" / "eap1_lowlight.yaml").read_text(encoding="utf-8"))
    source = ROOT / config["dataset"]["local_root"]
    REPORTS.mkdir(parents=True, exist_ok=True)
    started = time.time()
    audit = tools.audit_dataset(source, workers=4, near_duplicates=True)
    audit["root"] = config["dataset"]["local_root"]
    audit["duration_seconds"] = time.time() - started
    audit["dataset_version"] = config["dataset"]["version"]
    audit["license_note"] = ("Combined CME-1/CME-OPT1 dataset; per-source licences are recorded in "
                             "CMEOPT1_reference_attributions.csv and earlier task reports, not re-verified by EAP-1.")
    plan = tools.select_training_augmentations(
        [p.name for p in (source / "images" / "train").iterdir() if p.suffix.lower() in tools.IMAGE_SUFFIXES],
        config["augmentation"]["train_fraction"], config["seed"])
    audit["planned_training_augmentations"] = dict(count=len(plan), profiles={p: sum(1 for _, q in plan if q == p) for p in degradations.TRAIN_PROFILES})
    audit["contact_sheet"] = contact_sheet(source, config["seed"], REPORTS / "augmentation_contact_sheet.png")
    (REPORTS / "dataset_audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    print(json.dumps({k: audit[k] for k in ("splits", "filename_overlap", "near_duplicate_cross_split")}, indent=1)[:4000])
    print("invalid images", len(audit["invalid_images"]), "invalid labels", len(audit["invalid_labels"]),
          "exact cross-split duplicates", len(audit["exact_cross_split_duplicates"]))


if __name__ == "__main__":
    main()
