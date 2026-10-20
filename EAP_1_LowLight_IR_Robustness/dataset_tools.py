"""Dataset validation and the training-only EAP-1 robustness dataset builder."""
import hashlib
import json
import os
import shutil
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import cv2
import numpy as np
import yaml

try:
    from . import degradations
except ImportError:  # executed as a flat module inside the Modal image
    import degradations

SPLITS = ("train", "val", "test")
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
AUGMENT_PREFIX = "eap1aug_"


class DatasetError(RuntimeError):
    """Raised with an actionable message when a dataset/checkpoint input is unusable."""


def sha256_file(path, chunk=1 << 20):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def load_names(data_yaml):
    data_yaml = Path(data_yaml)
    if not data_yaml.is_file():
        raise DatasetError(f"Dataset YAML not found: {data_yaml}. Restore the CME-OPT1 v3 dataset first.")
    names = yaml.safe_load(data_yaml.read_text(encoding="utf-8"))["names"]
    names = dict(enumerate(names)) if isinstance(names, list) else {int(k): v for k, v in names.items()}
    return names


def parse_label_file(path, nc):
    """Return (boxes, errors). A box is (class_id, cx, cy, w, h); invalid rows are reported, never fixed."""
    boxes, errors = [], []
    text = Path(path).read_text(encoding="utf-8").strip()
    for number, row in enumerate(text.splitlines() if text else [], 1):
        parts = row.split()
        if len(parts) != 5:
            errors.append(f"line {number}: expected 5 values, found {len(parts)}")
            continue
        try:
            cls = int(parts[0]) if float(parts[0]).is_integer() else None
            cx, cy, w, h = map(float, parts[1:])
        except ValueError:
            errors.append(f"line {number}: non-numeric value")
            continue
        if cls is None or not 0 <= cls < nc:
            errors.append(f"line {number}: class id {parts[0]} outside 0..{nc - 1}")
            continue
        if not all(np.isfinite([cx, cy, w, h])) or w <= 0 or h <= 0:
            errors.append(f"line {number}: non-positive or non-finite box size")
            continue
        tol = 1e-3
        if cx - w / 2 < -tol or cy - h / 2 < -tol or cx + w / 2 > 1 + tol or cy + h / 2 > 1 + tol:
            errors.append(f"line {number}: box extends outside normalized image")
            continue
        boxes.append((cls, cx, cy, w, h))
    return boxes, errors


def label_for(image_path):
    parts = list(Path(image_path).parts)
    index = len(parts) - 1 - parts[::-1].index("images")
    parts[index] = "labels"
    return Path(*parts).with_suffix(".txt")


def inspect_image(path):
    """Decode safely; return dict with dims/luma or an error. Never raises for corrupt files."""
    try:
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    except cv2.error as exc:
        return dict(error=f"decode error: {exc}")
    if image is None or image.size == 0:
        return dict(error="unreadable or corrupted image")
    b, g, r = cv2.split(image)
    monochrome = bool(np.array_equal(b, g) and np.array_equal(g, r))
    return dict(width=int(image.shape[1]), height=int(image.shape[0]), luma=degradations.luma(image),
                monochrome=monochrome)


def _audit_one(args):
    path, nc = args
    info = inspect_image(path)
    label = label_for(path)
    if label.is_file():
        boxes, errors = parse_label_file(label, nc)
    else:
        boxes, errors = [], ["missing label file"]
    return dict(name=Path(path).name, sha256=sha256_file(path), boxes=[b[0] for b in boxes], label_errors=errors, **info)


def audit_dataset(root, workers=4, near_duplicates=True):
    """Validate images, labels and split integrity of a YOLO dataset; report-only, never modifies files."""
    root = Path(root)
    names = load_names(root / "data.yaml")
    nc = len(names)
    report = dict(root=str(root), class_names=names, splits={}, invalid_images=[], invalid_labels=[])
    hashes = {}
    records = {}
    for split in SPLITS:
        folder = root / "images" / split
        if not folder.is_dir():
            raise DatasetError(f"Missing split directory: {folder}")
        paths = sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
        with ProcessPoolExecutor(workers) as pool:
            rows = list(pool.map(_audit_one, [(p, nc) for p in paths], chunksize=32))
        records[split] = rows
        classes = Counter(c for row in rows for c in row["boxes"])
        lumas = [row["luma"] for row in rows if "luma" in row]
        report["splits"][split] = dict(
            images=len(rows), objects=sum(classes.values()), background_images=sum(1 for r in rows if not r["boxes"]),
            class_objects={names[c]: classes.get(c, 0) for c in range(nc)},
            luma=dict(mean=float(np.mean(lumas)), p10=float(np.percentile(lumas, 10)), p50=float(np.median(lumas)),
                      min=float(np.min(lumas))) if lumas else None,
            luma_below_80=sum(1 for v in lumas if v < 80), luma_below_50=sum(1 for v in lumas if v < 50),
            monochrome_images=sum(1 for r in rows if r.get("monochrome")),
            augmented_eap1_files=sum(1 for r in rows if r["name"].startswith(AUGMENT_PREFIX)))
        report["invalid_images"] += [dict(split=split, name=r["name"], error=r["error"]) for r in rows if "error" in r]
        report["invalid_labels"] += [dict(split=split, name=r["name"], errors=r["label_errors"]) for r in rows if r["label_errors"]]
        for row in rows:
            hashes.setdefault(row["sha256"], []).append((split, row["name"]))
    report["exact_cross_split_duplicates"] = [v for v in hashes.values() if len({s for s, _ in v}) > 1]
    report["exact_within_split_duplicates"] = sum(1 for v in hashes.values() if len(v) > 1 and len({s for s, _ in v}) == 1)
    names_by_split = {s: {r["name"] for r in records[s]} for s in SPLITS}
    report["filename_overlap"] = {f"{a}-{b}": len(names_by_split[a] & names_by_split[b])
                                  for i, a in enumerate(SPLITS) for b in SPLITS[i + 1:]}
    if near_duplicates:
        report["near_duplicate_cross_split"] = near_duplicate_pairs(root, records)
    report["genuine_infrared_images"] = 0
    report["genuine_infrared_note"] = ("No source metadata identifies any image as infrared/thermal; monochrome "
                                       "images are counted but are not claimed as infrared.")
    return report


def _phash(path):
    import imagehash
    from PIL import Image
    try:
        with Image.open(path) as image:
            return str(imagehash.phash(image.convert("L")))
    except OSError:
        return None


def near_duplicate_pairs(root, records, max_distance=4):
    """Perceptual-hash comparison of val/test against train (Hamming <= max_distance)."""
    import imagehash
    hashes = {}
    with ProcessPoolExecutor(4) as pool:
        for split in SPLITS:
            paths = [root / "images" / split / r["name"] for r in records[split]]
            hashes[split] = [(p.name, h) for p, h in zip(paths, pool.map(_phash, paths, chunksize=64)) if h]
    train = np.array([[int(c, 16) for c in h] for _, h in hashes["train"]], dtype=np.uint8)
    bits = np.unpackbits(train[:, :, None], axis=2)[:, :, 4:].reshape(len(train), -1)
    found = {}
    for split in ("val", "test"):
        pairs = []
        for name, h in hashes[split]:
            row = np.unpackbits(np.array([int(c, 16) for c in h], np.uint8)[:, None], axis=1)[:, 4:].reshape(-1)
            distance = (bits != row).sum(1)
            hit = int(distance.argmin())
            if distance[hit] <= max_distance:
                pairs.append(dict(eval_image=name, train_image=hashes["train"][hit][0], hamming=int(distance[hit])))
        found[split] = dict(count=len(pairs), max_hamming=max_distance, examples=pairs[:25])
    return found


def _link_or_copy(source, target):
    try:
        os.symlink(source, target)
    except (OSError, NotImplementedError):
        shutil.copy2(source, target)


def _degrade_one(args):
    source, target, profile, seed, purpose = args
    image = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if image is None:
        raise DatasetError(f"Unreadable source image: {source}")
    out, params = degradations.apply(image, profile, degradations.rng_for(seed, purpose, Path(source).name))
    if not cv2.imwrite(str(target), out, [cv2.IMWRITE_JPEG_QUALITY, 95]):
        raise DatasetError(f"Could not write {target}")
    return dict(source=Path(source).name, file=Path(target).name, profile=profile, params=params)


def select_training_augmentations(train_names, fraction, seed):
    """Deterministic one-profile-per-selected-image plan (no stacked near-identical copies)."""
    plan = []
    for name in sorted(train_names):
        rng = degradations.rng_for(seed, "select", name)
        if rng.random() < fraction:
            plan.append((name, degradations.TRAIN_PROFILES[int(rng.integers(len(degradations.TRAIN_PROFILES)))]))
    return plan


def build_robust_dataset(source, output, config, workers=8):
    """Build train (original + training-only degraded copies), untouched val/test, and
    fixed synthetic evaluation domains. Originals are linked/copied, never modified."""
    source, output = Path(source), Path(output)
    if output.exists():
        raise DatasetError(f"Refusing to overwrite existing dataset build: {output}")
    names = load_names(source / "data.yaml")
    seed = int(config["seed"])
    jobs, manifest = [], dict(seed=seed, source=str(source), train_fraction=config["augmentation"]["train_fraction"])
    for split in SPLITS:
        (output / "images" / split).mkdir(parents=True)
        (output / "labels" / split).mkdir(parents=True)
        for image in sorted((source / "images" / split).iterdir()):
            if image.suffix.lower() in IMAGE_SUFFIXES:
                _link_or_copy(image.resolve(), output / "images" / split / image.name)
                shutil.copy2(label_for(image), output / "labels" / split / (image.stem + ".txt"))
    train_names = [p.name for p in (source / "images" / "train").iterdir() if p.suffix.lower() in IMAGE_SUFFIXES]
    plan = select_training_augmentations(train_names, config["augmentation"]["train_fraction"], seed)
    for name, profile in plan:
        stem = Path(name).stem
        target = output / "images" / "train" / f"{AUGMENT_PREFIX}{profile}__{stem}.jpg"
        shutil.copy2(source / "labels" / "train" / f"{stem}.txt", output / "labels" / "train" / f"{target.stem}.txt")
        jobs.append((source / "images" / "train" / name, target, profile, seed, "train"))
    # Fixed evaluation domains for val (checkpoint selection) and test (final report).
    val_domains = {}
    for split in ("val", "test"):
        for domain in degradations.EVAL_DOMAINS:
            folder = output / "domains" / domain
            (folder / "images" / split).mkdir(parents=True, exist_ok=True)
            (folder / "labels" / split).mkdir(parents=True, exist_ok=True)
            for image in sorted((source / "images" / split).iterdir()):
                if image.suffix.lower() not in IMAGE_SUFFIXES:
                    continue
                shutil.copy2(label_for(image), folder / "labels" / split / (image.stem + ".txt"))
                jobs.append((image, folder / "images" / split / (image.stem + ".jpg"), domain, seed, f"eval-{split}"))
    with ProcessPoolExecutor(workers) as pool:
        produced = list(pool.map(_degrade_one, jobs, chunksize=16))
    train_aug = [p for p in produced if p["file"].startswith(AUGMENT_PREFIX)]
    manifest.update(
        original_counts={s: len(list((source / "images" / s).iterdir())) for s in SPLITS},
        train_augmented=len(train_aug), train_total=len(list((output / "images" / "train").iterdir())),
        train_profile_counts=dict(Counter(p["profile"] for p in train_aug)),
        synthetic_ir_style_is_genuine_ir=False,
        eval_domain_images={d: {s: len(list((output / "domains" / d / "images" / s).iterdir())) for s in ("val", "test")}
                            for d in degradations.EVAL_DOMAINS},
        augmentations=train_aug)
    val_paths = [str(output / "images" / "val")] + [str(output / "domains" / d / "images" / "val") for d in degradations.EVAL_DOMAINS]
    write_yaml(output / "data.yaml", dict(path=str(output), train="images/train", val=val_paths, test="images/test", names=names))
    for domain in degradations.EVAL_DOMAINS:
        root = output / "domains" / domain
        write_yaml(root / "data.yaml", dict(path=str(root), train="images/val", val="images/val", test="images/test", names=names))
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def build_natural_dark(source, output, threshold):
    """Real (unmodified) images whose mean luma is below threshold: a naturally dark subset."""
    names = load_names(Path(source) / "data.yaml")
    selected = {}
    for split in ("val", "test"):
        (output / "images" / split).mkdir(parents=True, exist_ok=True)
        (output / "labels" / split).mkdir(parents=True, exist_ok=True)
        chosen = []
        for image in sorted((Path(source) / "images" / split).iterdir()):
            if image.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            info = inspect_image(image)
            if "luma" in info and info["luma"] < threshold:
                _link_or_copy(image.resolve(), output / "images" / split / image.name)
                shutil.copy2(label_for(image), output / "labels" / split / (image.stem + ".txt"))
                chosen.append(image.name)
        selected[split] = chosen
    write_yaml(output / "data.yaml", dict(path=str(output), train="images/val", val="images/val", test="images/test", names=names))
    return selected


def write_yaml(path, data):
    Path(path).write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
