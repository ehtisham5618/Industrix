"""EAP-1 dataset, augmentation, evaluation and offline tests (no training run required)."""
import ast
import json
import socket
import sys
import tracemalloc
from pathlib import Path
import cv2
import numpy as np
import pytest
import yaml

TASK = Path(__file__).resolve().parents[1]
ROOT = TASK.parent
sys.path.insert(0, str(TASK))
import dataset_tools as tools  # noqa: E402
import degradations  # noqa: E402
import evaluate as ev  # noqa: E402

CONFIG = yaml.safe_load((TASK / "configs" / "eap1_lowlight.yaml").read_text(encoding="utf-8"))
NAMES = ["baekra", "color issues", "contamination", "cut", "gray stitch", "selvet", "stain",
         "chemical hazard", "fire", "no helmet", "smoke", "water leak"]
ALL_PROFILES = degradations.TRAIN_PROFILES + degradations.EVAL_DOMAINS


def _image(seed=0, h=96, w=128):
    rng = np.random.default_rng(seed)
    image = rng.integers(40, 220, (h, w, 3), dtype=np.uint8)
    cv2.rectangle(image, (30, 20), (90, 70), (250, 250, 250), -1)
    return image


def make_dataset(root, per_split=3, label="3 0.5 0.5 0.4 0.4\n"):
    for split in tools.SPLITS:
        (root / "images" / split).mkdir(parents=True)
        (root / "labels" / split).mkdir(parents=True)
        for i in range(per_split):
            cv2.imwrite(str(root / "images" / split / f"{split}_{i}.jpg"), _image(hash((split, i)) % 1000))
            (root / "labels" / split / f"{split}_{i}.txt").write_text(label)
    tools.write_yaml(root / "data.yaml", dict(path=str(root), train="images/train", val="images/val",
                                             test="images/test", names=NAMES))
    return root


# ---- Dataset validation -------------------------------------------------------------
def test_valid_dataset_loads(tmp_path):
    report = tools.audit_dataset(make_dataset(tmp_path / "d"), workers=1, near_duplicates=False)
    assert not report["invalid_images"] and not report["invalid_labels"]
    assert report["splits"]["train"]["objects"] == 3
    assert report["splits"]["test"]["class_objects"]["cut"] == 3


def test_corrupted_image_reported_not_raised(tmp_path):
    root = make_dataset(tmp_path / "d")
    (root / "images" / "val" / "val_0.jpg").write_bytes(b"not an image")
    report = tools.audit_dataset(root, workers=1, near_duplicates=False)
    assert report["invalid_images"] == [dict(split="val", name="val_0.jpg", error="unreadable or corrupted image")]


@pytest.mark.parametrize("row,fragment", [("12 0.5 0.5 0.1 0.1", "class id"), ("-1 0.5 0.5 0.1 0.1", "class id"),
                                          ("1.5 0.5 0.5 0.1 0.1", "class id"), ("2 0.5 0.5 0 0.1", "non-positive"),
                                          ("2 0.95 0.5 0.3 0.1", "outside"), ("2 0.5 0.5 0.1", "expected 5"),
                                          ("2 a 0.5 0.1 0.1", "non-numeric"), ("2 nan 0.5 0.1 0.1", "non-finite")])
def test_malformed_labels_rejected(tmp_path, row, fragment):
    path = tmp_path / "x.txt"
    path.write_text(row + "\n")
    boxes, errors = tools.parse_label_file(path, 12)
    assert boxes == [] and fragment in errors[0]


def test_missing_dataset_has_actionable_error(tmp_path):
    with pytest.raises(tools.DatasetError, match="Dataset YAML not found"):
        tools.audit_dataset(tmp_path / "missing")


def test_cross_split_duplicate_detected(tmp_path):
    root = make_dataset(tmp_path / "d")
    (root / "images" / "test" / "dup.jpg").write_bytes((root / "images" / "train" / "train_0.jpg").read_bytes())
    (root / "labels" / "test" / "dup.txt").write_text("3 0.5 0.5 0.4 0.4\n")
    report = tools.audit_dataset(root, workers=1, near_duplicates=True)
    assert any({s for s, _ in group} == {"train", "test"} for group in report["exact_cross_split_duplicates"])
    assert report["near_duplicate_cross_split"]["test"]["count"] >= 1


# ---- Augmentation -------------------------------------------------------------------
@pytest.mark.parametrize("profile", ALL_PROFILES)
def test_degradation_preserves_geometry_and_is_deterministic(profile):
    image = _image()
    first, params = degradations.apply(image, profile, degradations.rng_for(42, "t", "a.jpg"))
    second, params2 = degradations.apply(image, profile, degradations.rng_for(42, "t", "a.jpg"))
    assert first.shape == image.shape and first.dtype == np.uint8
    assert np.array_equal(first, second) and params == params2


@pytest.mark.parametrize("profile", ["lowlight", "synthetic_lowlight", "synthetic_very_dark"])
def test_lowlight_profiles_darken(profile):
    image = _image()
    out, _ = degradations.apply(image, profile, degradations.rng_for(1, "t", "b"))
    assert degradations.luma(out) < degradations.luma(image)


def test_unknown_profile_and_bad_image_rejected():
    with pytest.raises(ValueError):
        degradations.apply(_image(), "thermal_real", degradations.rng_for(1, "t", "x"))
    with pytest.raises(ValueError):
        degradations.apply(np.zeros((4, 4), np.uint8), "lowlight", degradations.rng_for(1, "t", "x"))


def test_synthetic_ir_is_labelled_synthetic():
    out, _ = degradations.apply(_image(), "synthetic_ir_style", degradations.rng_for(1, "t", "x"))
    assert np.array_equal(out[..., 0], out[..., 1])
    assert "synthetic_ir_style" in degradations.SYNTHETIC_IR and "ir" not in degradations.TRAIN_PROFILES


def test_build_keeps_splits_clean_and_labels_unchanged(tmp_path):
    source = make_dataset(tmp_path / "src", per_split=8)
    config = dict(CONFIG, augmentation=dict(CONFIG["augmentation"], train_fraction=0.5))
    manifest = tools.build_robust_dataset(source, tmp_path / "out", config, workers=1)
    out = tmp_path / "out"
    augmented = [p for p in (out / "images" / "train").iterdir() if p.name.startswith(tools.AUGMENT_PREFIX)]
    assert len(augmented) == manifest["train_augmented"] > 0
    assert manifest["original_counts"] == {"train": 8, "val": 8, "test": 8}
    assert manifest["synthetic_ir_style_is_genuine_ir"] is False
    for split in ("val", "test"):  # no training augmentation leaks into evaluation splits
        assert not any(p.name.startswith(tools.AUGMENT_PREFIX) for p in (out / "images" / split).iterdir())
        assert len(list((out / "images" / split).iterdir())) == 8
    for image in augmented:
        stem = image.stem.split("__", 1)[1]
        assert (out / "labels" / "train" / f"{image.stem}.txt").read_text() == (source / "labels" / "train" / f"{stem}.txt").read_text()
        assert cv2.imread(str(image)).shape == cv2.imread(str(source / "images" / "train" / f"{stem}.jpg")).shape
    sources = [a["source"] for a in manifest["augmentations"]]
    assert len(sources) == len(set(sources))  # at most one degraded copy per image
    report = tools.audit_dataset(out, workers=1, near_duplicates=False)
    assert not report["invalid_labels"] and not report["exact_cross_split_duplicates"]
    data = yaml.safe_load((out / "data.yaml").read_text())
    assert data["test"] == "images/test" and all(Path(v).parts[-2:] == ("images", "val") for v in data["val"])


def test_build_refuses_overwrite_and_is_reproducible(tmp_path):
    source = make_dataset(tmp_path / "src", per_split=6)
    first = tools.build_robust_dataset(source, tmp_path / "a", CONFIG, workers=1)
    second = tools.build_robust_dataset(source, tmp_path / "b", CONFIG, workers=1)
    assert first["augmentations"] == second["augmentations"]
    for item in first["augmentations"]:
        assert tools.sha256_file(tmp_path / "a/images/train" / item["file"]) == tools.sha256_file(tmp_path / "b/images/train" / item["file"])
    with pytest.raises(tools.DatasetError, match="Refusing to overwrite"):
        tools.build_robust_dataset(source, tmp_path / "a", CONFIG, workers=1)


def test_selection_plan_is_deterministic():
    names = [f"img_{i}.jpg" for i in range(400)]
    plan = tools.select_training_augmentations(names, 0.35, 42)
    assert plan == tools.select_training_augmentations(names, 0.35, 42)
    assert 0.25 < len(plan) / 400 < 0.45
    assert {p for _, p in plan} <= set(degradations.TRAIN_PROFILES)


# ---- Evaluation and reporting --------------------------------------------------------
def _report(**overrides):
    base = dict(precision=0.8, recall=0.7, map50=0.75, map50_95=0.45, settings=dict(imgsz=640, batch=32, conf=0.001, iou=0.7),
                counts=dict(images=10, objects=12), per_class={"fire": dict(ap50=0.9, ap50_95=0.6)})
    base.update(overrides)
    return base


def test_report_validation_rejects_missing_or_fabricated_values():
    assert ev.validate_report(_report())
    for bad in (dict(map50=None), dict(precision=float("nan")), dict(recall=1.2), dict(counts=dict(images=0))):
        with pytest.raises(ValueError):
            ev.validate_report(_report(**bad))


def test_comparison_requires_equivalent_settings():
    delta = ev.compare(_report(), _report(map50=0.8, per_class={"fire": dict(ap50=0.85, ap50_95=0.6)}))
    assert delta["overall"]["map50"] == pytest.approx(0.05)
    assert delta["per_class"]["fire"]["delta_ap50"] == pytest.approx(-0.05)
    with pytest.raises(ValueError, match="equivalent"):
        ev.compare(_report(), _report(settings=dict(imgsz=320, batch=32, conf=0.001, iou=0.7)))


def test_class_map_mismatch_rejected():
    ev.check_class_map(dict(enumerate(NAMES)), dict(enumerate(NAMES)))
    with pytest.raises(tools.DatasetError):
        ev.check_class_map(dict(enumerate(reversed(NAMES))), dict(enumerate(NAMES)))


def test_missing_checkpoint_has_actionable_error(tmp_path):
    source = make_dataset(tmp_path / "d")
    with pytest.raises(tools.DatasetError, match="Checkpoint not found"):
        ev.evaluate(tmp_path / "none.pt", source / "data.yaml", "test", CONFIG["evaluation"], tmp_path, "x")


def test_config_class_count_and_source_checkpoint():
    names = tools.load_names(ROOT / "Hazard_Expansion/configs/12class_data.yaml") \
        if (ROOT / "Hazard_Expansion/configs/12class_data.yaml").is_file() else dict(enumerate(NAMES))
    assert CONFIG["dataset"]["nc"] == len(names) == 12
    assert CONFIG["training"]["epochs"] >= CONFIG["training"]["patience"] > 0
    assert CONFIG["evaluation"]["conf"] == 0.001


@pytest.mark.skipif(not (ROOT / "Backend/best.pt").is_file(), reason="production checkpoint not present locally")
def test_production_checkpoint_hash_and_class_map():
    assert tools.sha256_file(ROOT / "Backend/best.pt") == CONFIG["source_checkpoint"]["sha256"]
    from ultralytics import YOLO
    ev.check_class_map(YOLO(str(ROOT / "Backend/best.pt")).names, dict(enumerate(NAMES)))


CANDIDATE = TASK / "runtime" / "eap1_lowlight_v1" / "best.pt"


@pytest.mark.skipif(not CANDIDATE.is_file(), reason="candidate checkpoint not fetched")
def test_candidate_checkpoint_loads_with_same_class_map():
    from ultralytics import YOLO
    model = YOLO(str(CANDIDATE))
    ev.check_class_map(model.names, dict(enumerate(NAMES)))
    result = model.predict(_image(h=320, w=320), imgsz=320, verbose=False, device="cpu")[0]
    assert result.boxes is not None


SUMMARY = ROOT / "reports" / "eap1" / "eap1_robustness_summary.json"


@pytest.mark.skipif(not SUMMARY.is_file(), reason="summary not generated yet")
def test_summary_has_no_fabricated_or_successful_interrupted_training():
    summary = json.loads(SUMMARY.read_text())
    assert summary["task"] == "EAP-1"
    if summary["training"]["status"] != "completed":
        assert summary["dod"]["Fine-tuning completed"] != "PASS"
    for side in ("baseline", "candidate"):
        for domain, report in summary["evaluation"].get(side, {}).items():
            ev.validate_report(report)
    assert summary["genuine_ir"]["evaluated"] is False


# ---- Offline / resource --------------------------------------------------------------
def test_pipeline_modules_have_no_network_clients():
    banned = {"requests", "urllib", "httpx", "kagglehub", "boto3", "mlflow"}
    for module in ("degradations.py", "dataset_tools.py", "evaluate.py", "pipeline.py", "local_audit.py"):
        tree = ast.parse((TASK / module).read_text(encoding="utf-8"))
        imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        imported |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        assert not imported & banned, module


def test_build_and_audit_make_no_socket_calls(tmp_path, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("network access attempted")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    source = make_dataset(tmp_path / "src", per_split=3)
    tools.build_robust_dataset(source, tmp_path / "out", CONFIG, workers=1)
    tools.audit_dataset(tmp_path / "out", workers=1, near_duplicates=False)


def test_repeated_degradation_memory_is_bounded():
    image = _image(h=480, w=640)
    for _ in range(5):
        degradations.apply(image, "synthetic_cctv", degradations.rng_for(1, "m", "w"))
    tracemalloc.start()
    baseline = tracemalloc.take_snapshot()
    for i in range(200):
        degradations.apply(image, ALL_PROFILES[i % len(ALL_PROFILES)], degradations.rng_for(1, "m", str(i)))
    growth = sum(s.size_diff for s in tracemalloc.take_snapshot().compare_to(baseline, "filename"))
    tracemalloc.stop()
    assert growth < 2 * 1024 * 1024  # bytes retained after 200 transforms of a 640x480 image
