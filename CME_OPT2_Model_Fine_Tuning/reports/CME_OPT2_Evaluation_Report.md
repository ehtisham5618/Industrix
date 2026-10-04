# CME-OPT2 Evaluation Report

Acceptance: **FAIL — numerical target shortfall**.

Selected run: `cme_opt2_B_expC_focal_cosine`. Official A uses COCO pretrained yolov8s.pt, SGD lr0=.01. B starts from registered Experiment C and raises cls gain .5 to 2.0. C uses the same Experiment C initialization with AdamW lr0=.001, zero bias warmup, cls=.5 and focal class weights chemical=4 / smoke=2 / others=1. All runs retain the same focal gamma/alpha, cosine factor, batch, image size, seed, maximum epochs and patience on CME-OPT1 v3.
Dataset: 5,479 train / 777 validation / 334 test images; all 12 classes, 10,352 annotations. Evaluation files retain original SHA256 hashes.
The original dataset already shares Roboflow source families across splits; CME-OPT1 introduced no new leakage. Generalization claims remain limited by inherited family overlap.

Historical Experiment C chemical AP50 was 49.1327% on validation (53 chemical annotations). It is retained as history, not compared as a test metric.
The table below re-evaluates both checkpoints with the same untouched test split: imgsz=640, conf=.001, IoU=.7, max_det=300, no TTA, FP32.
The test split contains only four chemical objects: its AP has substantial sampling uncertainty.

## Training configuration

| Parameter | Value |
|---|---|
| Model | YOLOv8s / cme1-expanded-12class-v1 (baseline.pt) |
| Dataset | combined-12class-v3-hardnegative |
| Starting checkpoint SHA256 | 6e64a19d83f09b7b2a92fddf23a5161734295c2a183af08ee1802065bd36995b |
| Requested / completed epochs | 50 / 11 |
| Best validation epoch | 1 |
| Early stop | True |
| Runtime | {'python': '3.11.12', 'torch': '2.10.0+cu128', 'ultralytics': '8.4.24', 'cuda': '12.8', 'gpu': 'NVIDIA A10', 'vram_bytes': 23684841472} |
| Focal gamma / alpha | 1.5 / 0.25 |
| Theoretical cosine endpoint | 0.01 × 0.001 = 1e-05 |
| Actual final LR | {'epoch': '11', 'lr_pg0': '0.009046039886902862', 'lr_pg1': '0.009046039886902862', 'lr_pg2': '0.009046039886902862'} |
| Classification class weights | all 1 |
| epochs | 50 |
| patience | 10 |
| imgsz | 640 |
| batch | 16 |
| optimizer | SGD |
| lr0 | 0.01 |
| lrf | 0.001 |
| cos_lr | True |
| momentum | 0.937 |
| weight_decay | 0.0005 |
| warmup_epochs | 3.0 |
| seed | 42 |
| deterministic | True |
| amp | True |
| hsv_h | 0.01 |
| hsv_s | 0.3 |
| hsv_v | 0.2 |
| degrees | 0.0 |
| translate | 0.1 |
| scale | 0.3 |
| fliplr | 0.5 |
| flipud | 0.0 |
| mosaic | 0.5 |
| mixup | 0.0 |
| close_mosaic | 10 |
| workers | 4 |
| plots | True |
| save | True |
| exist_ok | False |
| data | /__modal/volumes/vo-mGfQgI2JSR3Hn9Abh7h8Vc/dataset/data.yaml |
| device | 0 |
| project | /__modal/volumes/vo-mGfQgI2JSR3Hn9Abh7h8Vc/runs |
| name | cme_opt2_B_expC_focal_cosine |
| cls | 2.0 |

Focal implementation replaces only the elementwise BCE callable in v8DetectionLoss. Soft task-aligned targets, sum/target-score normalization, box loss and DFL remain unchanged. Upstream FocalLoss is not used directly because its internal class reduction would change the detection loss scale. Gamma=1.5 and alpha=.25 follow the pinned upstream defaults; conservative online augmentation limits compounding the existing offline augmentations.
Training classification losses use focal loss; upstream EMA validation losses use BCE. Those two loss columns have different scales; validation AP, rather than a train/validation classification-loss ratio, drives checkpoint selection.

Selection: Across A/B/C: retain candidates with validation mAP50>=.72 when any qualify; highest validation chemical AP50 then validation mAP50-95. If none qualify, highest validation mAP50-95. Each candidate uses its best validation mAP50-95 checkpoint. Test data unused.. No test-driven tuning.

## Controlled experiment comparison (validation)

| Run | Initialization | Classification gain | Epochs | Best epoch | Val mAP50 | Val chemical AP50 | Selected |
|---|---|---:|---:|---:|---:|---:|---|
| cme_opt2_yolov8s_focal_cosine | yolov8s.pt | 0.5 | 50 | 48 | 47.421% | 21.658% | False |
| cme_opt2_B_expC_focal_cosine | cme1-expanded-12class-v1 (baseline.pt) | 2.0 | 11 | 1 | 77.278% | 45.429% | True |
| cme_opt2_C_targeted_focal_cosine | cme1-expanded-12class-v1 (baseline.pt) | 0.5 | 11 | 1 | 68.020% | 8.970% | False |

cme_opt2_yolov8s_focal_cosine: Official requested configuration; resumed after Modal client network timeout.
Infrastructure recovery: {'completed_before_disconnect': 19, 'checkpoint_sha256': '208e99ed2eb539be6a8c6ffde3ee492e293bccd7ee7147c6eaf769c900472ad7', 'checkpoint_backup': '/__modal/volumes/vo-mGfQgI2JSR3Hn9Abh7h8Vc/official_A_resume_epoch_19.pt', 'optimizer_and_scaler_restored': True, 'parameters_unchanged': True, 'limitation': 'Augmentation RNG/early-stopping in-memory state reinitializes on upstream resume; not bitwise equivalent to uninterrupted execution'}. The original optimizer/scaler and requested settings were restored.
cme_opt2_B_expC_focal_cosine: Official A validation mAP50=16.4% at epoch 12 versus historical Experiment C=76.6%; retain a trained 12-class head and raise cls gain .5 to 2.0 to compensate alpha=.25; no test feedback.
cme_opt2_C_targeted_focal_cosine: B selected validation chemical AP50=45.4% remains weak despite overall 77.3%; use AdamW lr=.001 and no large bias warmup to reduce pretrained-head disruption, focal class weights 4 chemical / 2 smoke to direct weak-class learning; no test feedback.

## Held-out test comparison

| Metric | Experiment C | CME-OPT2 |
|---|---:|---:|
| precision | 77.748% | 73.779% |
| recall | 75.905% | 76.450% |
| map50 | 77.796% | 78.156% |
| map50_95 | 48.939% | 49.094% |

| Class | C AP50 | New AP50 | Delta (pp) | New P | New R | New AP50-95 | Regression >5pp |
|---|---:|---:|---:|---:|---:|---:|---|
| baekra | 96.50 | 96.70 | +0.20 | 91.06 | 100.00 | 75.21 | False |
| color issues | 70.81 | 79.92 | +9.11 | 70.33 | 80.95 | 45.15 | False |
| contamination | 97.71 | 96.76 | -0.94 | 82.88 | 94.12 | 54.57 | False |
| cut | 79.50 | 68.85 | -10.65 | 66.16 | 74.88 | 47.47 | True |
| gray stitch | 80.13 | 82.66 | +2.53 | 77.82 | 75.00 | 53.51 | False |
| selvet | 91.67 | 91.98 | +0.30 | 69.30 | 84.48 | 66.27 | False |
| stain | 91.63 | 91.90 | +0.26 | 83.95 | 90.85 | 57.42 | False |
| chemical hazard | 28.92 | 42.39 | +13.47 | 52.39 | 25.00 | 29.89 | False |
| fire | 65.63 | 63.10 | -2.53 | 71.11 | 67.16 | 28.42 | False |
| no helmet | 88.18 | 92.05 | +3.87 | 87.53 | 88.89 | 51.74 | False |
| smoke | 61.49 | 54.52 | -6.97 | 56.46 | 54.90 | 27.89 | True |
| water leak | 81.37 | 77.04 | -4.33 | 76.37 | 81.16 | 51.58 | False |

Chemical absolute change: +13.468 percentage points; relative change: 46.567%.
Chemical AP50 ≥65%: **FAIL** (42.391%).
Overall mAP50 ≥72%: **PASS** (78.156%).

## Confusion and limitations

Experiment C, chemical hazard: true detections=1, background misses=2, background false positives=0. Counts use the validator's confusion threshold and are distinct from AP integration.
CME-OPT2, chemical hazard: true detections=1, background misses=2, background false positives=1. Counts use the validator's confusion threshold and are distinct from AP integration.
Experiment C, smoke: true detections=32, background misses=19, background false positives=18. Counts use the validator's confusion threshold and are distinct from AP integration.
CME-OPT2, smoke: true detections=32, background misses=19, background false positives=33. Counts use the validator's confusion threshold and are distinct from AP integration.

Per-class changes and complete confusion matrices are preserved rather than hiding regressions. The four-object chemical test sample and outdoor reference negatives limit any claim of factory deployment generalization. Offline synthetic augmentation and focal loss effects cannot be causally isolated without an ablation experiment.

Visual review of the unfiltered qualitative examples suggests a semantic label ambiguity: hazard_Chimney_smoke_smokehazard80_jpg.rf.0e7354d4ddbdfeae4b07f180f4ab63b6.jpg depicts chimney smoke but its original ground truth is chemical hazard (ID 7); both checkpoints predict smoke (ID 10). This is an inference from the image and recorded predictions, not an independently adjudicated relabeling. Dataset integrity validation checks syntax and hashes, not semantic label correctness. The original held-out label is preserved and its penalty remains in all reported metrics; independent label review belongs to a future dataset revision.

## Deployment and tracking

Deployment exported: True. Candidate SHA256: `c4aba081f6357e23a7370a5f7cf98eff2c6faa0c4c20a2d4dcb8bcabdd490061`.
Existing Experiment C backup: `CME_OPT2_Model_Fine_Tuning\runtime\baseline.pt`, SHA256 `6e64a19d83f09b7b2a92fddf23a5161734295c2a183af08ee1802065bd36995b`; remote copy `Modal industirx-cme-opt2:/baseline.pt`.
New version: `cme-opt2-focal-cosine-12class-v1`. MLflow run: `29ee74e5c2ac4dc3ad68f3aa9352fc4a` in the existing Vision-Driven-Industrial-Safety experiment; artifacts persist on Modal volume `/mlruns`.
Weights/data remain ignored by Git. GPU worker min_containers=0, scaledown_window=600; invocation exits when its work completes.
