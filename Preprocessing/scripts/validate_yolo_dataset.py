#!/usr/bin/env python3
"""
validate_yolo_dataset.py
========================
Standalone YOLO dataset validator for the Textile Defect Detection project.

Usage:
    python scripts/validate_yolo_dataset.py --dataset path/to/final_dataset

Returns exit code 0 on PASS, 1 on FAIL.
"""

import argparse
import json
import hashlib
import os
import sys
from pathlib import Path

import cv2
import yaml
from tqdm import tqdm

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
SPLITS = ["train", "val", "test"]


def load_yaml(yaml_path: Path) -> dict:
    with open(yaml_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def file_md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def is_image_readable(path: Path) -> bool:
    img = cv2.imread(str(path))
    return img is not None


def validate_label_line(line: str, num_classes: int) -> tuple[bool, str]:
    """Validate a single YOLO annotation line. Returns (valid, reason)."""
    parts = line.strip().split()
    if len(parts) != 5:
        return False, f"Expected 5 fields, got {len(parts)}"
    try:
        cls = int(parts[0])
        xc, yc, w, h = float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
    except ValueError:
        return False, "Non-numeric fields"

    import math
    for val in [xc, yc, w, h]:
        if math.isnan(val) or math.isinf(val):
            return False, "NaN or Inf value"

    if cls < 0 or cls >= num_classes:
        return False, f"Invalid class_id={cls} (valid 0-{num_classes-1})"
    if not (0 <= xc <= 1 and 0 <= yc <= 1):
        return False, f"x_center/y_center out of [0,1]: {xc},{yc}"
    if not (0 < w <= 1 and 0 < h <= 1):
        return False, f"width/height out of (0,1]: {w},{h}"
    tolerance = 1e-4  # Export rounding only; <0.52 px even at the largest source width
    if xc-w/2 < -tolerance or yc-h/2 < -tolerance or xc+w/2 > 1+tolerance or yc+h/2 > 1+tolerance:
        return False, "Box extends outside image"
    return True, "OK"


# -----------------------------------------------------------------------------
# Validators
# -----------------------------------------------------------------------------

def validate_dataset(dataset_root: Path, verbose: bool = False, report: Path | None = None) -> bool:
    """Run full validation. Returns True if PASS."""

    results = {
        "box_edge_tolerance": 1e-4,
        "rounded_edge_boxes": 0,
        "total_images": 0,
        "total_annotations": 0,
        "corrupted_images": 0,
        "invalid_labels": 0,
        "missing_labels": 0,
        "missing_images": 0,
        "invalid_class_ids": 0,
        "cross_split_duplicates": 0,
        "split_counts": {},
        "errors": [],
    }

    # -- data.yaml ------------------------------------------------------------
    yaml_path = dataset_root / "data.yaml"
    if not yaml_path.exists():
        print(f"[FAIL] data.yaml not found at {yaml_path}")
        return False

    cfg = load_yaml(yaml_path)
    class_names = cfg.get("names", [])
    if isinstance(class_names, dict):
        if set(class_names) != set(range(len(class_names))):
            print("[FAIL] names mapping must use contiguous integer IDs")
            return False
        class_names = [class_names[i] for i in range(len(class_names))]
    num_classes = len(class_names)
    if not num_classes or cfg.get("nc", num_classes) != num_classes:
        print("[FAIL] nc/names mismatch")
        return False
    if cfg.get("path") and Path(cfg["path"]).resolve() != dataset_root.resolve():
        print("WARNING: stale data.yaml path; validating explicitly supplied dataset root")
    print(f"\n  data.yaml      : FOUND")
    print(f"  Classes ({num_classes})    : {class_names}")

    # -- Splits ---------------------------------------------------------------
    split_image_hashes: dict[str, dict[str, str]] = {}  # split -> {hash: path}

    for split in SPLITS:
        configured = Path(cfg.get(split, f"images/{split}"))
        img_dir = configured if configured.is_absolute() else dataset_root / configured
        lbl_dir = dataset_root / "labels" / split

        if not img_dir.exists():
            if split == "test" and split not in cfg:
                print(f"  Split '{split}': MISSING (skipped - optional)")
                continue
            print(f"[FAIL] Required split '{split}' image dir missing: {img_dir}")
            results["errors"].append(f"Missing split: {split}")
            continue

        image_files = sorted(
            p for p in img_dir.iterdir()
            if p.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
        )
        if not image_files:
            results["errors"].append(f"Empty split: {split}")
        if len({p.stem for p in image_files}) != len(image_files):
            results["errors"].append(f"Ambiguous image stems: {split}")
        count = len(image_files)
        results["split_counts"][split] = count
        results["total_images"] += count
        split_image_hashes[split] = {}

        print(f"\n  -- Split: {split} ({count} images) --")

        for img_path in tqdm(image_files, desc=f"  Validating {split}", disable=not verbose):
            # Image readability
            if not is_image_readable(img_path):
                results["corrupted_images"] += 1
                results["errors"].append(f"CORRUPTED: {img_path}")
                if verbose:
                    print(f"    [CORRUPT] {img_path.name}")
                continue

            # MD5 for cross-split duplicate check
            md5 = file_md5(img_path)
            split_image_hashes[split][md5] = str(img_path)

            # Label existence
            if lbl_dir.exists():
                label_path = lbl_dir / (img_path.stem + ".txt")
                if not label_path.exists():
                    results["missing_labels"] += 1
                    results["errors"].append(f"MISSING_LABEL: {img_path.name}")
                    if verbose:
                        print(f"    [NO LABEL] {img_path.name}")
                else:
                    # Validate label contents
                    with open(label_path, "r", encoding="utf-8") as f:
                        lines = [l.strip() for l in f.readlines() if l.strip()]

                    results["total_annotations"] += len(lines)
                    for line in lines:
                        valid, reason = validate_label_line(line, num_classes)
                        if valid:
                            _, x, y, w, h = map(float, line.split())
                            if min(x-w/2,y-h/2)<0 or max(x+w/2,y+h/2)>1:
                                results["rounded_edge_boxes"] += 1
                        if not valid:
                            results["invalid_labels"] += 1
                            if reason.startswith("Invalid class_id"):
                                results["invalid_class_ids"] += 1
                            results["errors"].append(
                                f"INVALID_LABEL [{reason}]: {label_path.name}"
                            )
                            if verbose:
                                print(f"    [BAD LABEL] {label_path.name}: {reason}")
            else:
                results["missing_labels"] += 1
                results["errors"].append(f"MISSING label dir: {lbl_dir}")

        # Check label files without images
        if lbl_dir.exists():
            label_stems = {p.stem for p in lbl_dir.iterdir() if p.suffix == ".txt"}
            image_stems = {p.stem for p in image_files}
            orphan_labels = label_stems - image_stems
            for stem in orphan_labels:
                results["missing_images"] += 1
                results["errors"].append(f"ORPHAN_LABEL (no image): {stem}.txt")

    # -- Cross-split duplicate check ------------------------------------------
    print("\n  -- Cross-split duplicate check --")
    split_names = list(split_image_hashes.keys())
    for i in range(len(split_names)):
        for j in range(i + 1, len(split_names)):
            s1, s2 = split_names[i], split_names[j]
            common = set(split_image_hashes[s1].keys()) & set(split_image_hashes[s2].keys())
            if common:
                for h in common:
                    results["cross_split_duplicates"] += 1
                    results["errors"].append(
                        f"CROSS_SPLIT_DUPLICATE [{s1}<->{s2}]: {split_image_hashes[s1][h]}"
                    )
                    print(f"    [LEAK] {s1}<->{s2}: {Path(split_image_hashes[s1][h]).name}")

    # -- Final summary --------------------------------------------------------
    passed = (
        results["corrupted_images"] == 0
        and results["invalid_labels"] == 0
        and results["missing_labels"] == 0
        and results["cross_split_duplicates"] == 0
        and results["errors"] == []
    )

    print("\n" + "=" * 50)
    print("FINAL DATASET VALIDATION")
    print("=" * 50)
    print(f"Images:                 {results['total_images']}")
    print(f"Annotations:            {results['total_annotations']}")
    print(f"Classes:                {num_classes}")
    print()
    for split in SPLITS:
        cnt = results["split_counts"].get(split, "N/A")
        print(f"{split.capitalize()} images:          {cnt}")
    print()
    print(f"Corrupted images:       {results['corrupted_images']}")
    print(f"Invalid labels:         {results['invalid_labels']}")
    print(f"Missing labels:         {results['missing_labels']}")
    print(f"Cross-split duplicates: {results['cross_split_duplicates']}")
    print()
    print(f"YOLO format:            {'PASS' if passed else 'FAIL'}")
    print(f"data.yaml:              {'PASS' if yaml_path.exists() else 'FAIL'}")
    print("=" * 50)
    overall = " PASS" if passed else " FAIL"
    print(f"OVERALL: {overall}")
    print("=" * 50)

    if not passed and results["errors"]:
        print("\nErrors (first 20):")
        for e in results["errors"][:20]:
            print(f"  - {e}")

    if report:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps({**results, "passed": passed}, indent=2), encoding="utf-8")
    return passed


# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Validate a YOLOv8-format dataset directory."
    )
    parser.add_argument(
        "--dataset",
        type=str,
        required=True,
        help="Path to final_dataset/ root (must contain images/, labels/, data.yaml)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-file validation details",
    )
    parser.add_argument("--report", type=Path, help="Machine-readable JSON result")
    args = parser.parse_args()

    dataset_path = Path(args.dataset).resolve()
    if not dataset_path.exists():
        print(f"[ERROR] Dataset path does not exist: {dataset_path}")
        sys.exit(1)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(f"Validating dataset: {dataset_path}")
    passed = validate_dataset(dataset_path, verbose=args.verbose, report=args.report)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
