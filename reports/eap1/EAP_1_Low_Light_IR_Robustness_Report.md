# EAP-1 — Low-Light & CCTV Infrared Robustness Fine-Tuning: Production Review

**Implementation:** PASS  
**Model performance:** NOT VERIFIED - measured deltas reported; no numerical acceptance threshold defined  
**Production readiness:** NOT READY - candidate not export/benchmark validated, no genuine IR or real CCTV low-light labels, threshold undefined

All metrics are fractions reported as percentages (×100). Every value below was produced by the recorded EAP-1 run on Modal; no historical numbers are reused as fresh measurements.

## Lineage

- Source checkpoint: `Backend/best.pt` = `cme-opt2-focal-cosine-12class-v1`, SHA256 `c4aba081f6357e23a7370a5f7cf98eff2c6faa0c4c20a2d4dcb8bcabdd490061` (verified in the worker before use; unchanged).
- Candidate: `EAP_1_LowLight_IR_Robustness/runtime/eap1_lowlight_v1/best.pt` (local, ignored) and `industirx-eap1:/runs/eap1_lowlight_v1/weights/best.pt`, SHA256 `8e89f06c176a08484bb2ca4b388bcc37bdfbd2e3cfbc200ce42f9ded38b8be71`; local copy hash match: True.
- Dataset: `combined-12class-v3-hardnegative` archive SHA256 `2fd9cf17480f25487756f1113a7409e1616a9fd9e22e7347e1fa3b24ff8177e5`; 12-class map read from data.yaml and checked against both checkpoints.
- Training: status **completed**, 8/8 epochs, early stop: False, 10.0 min on NVIDIA A10 (2026-10-20T17:46:56.089456+00:00 → 2026-10-20T17:56:57.676233+00:00).

## Dataset audit

| Split | Images | Objects | Mean-luma < 80 |
|---|---:|---:|---:|
| train | 5479 | 8520 | 570 |
| val | 777 | 1334 | 95 |
| test | 334 | 498 | 24 |

Invalid images: 0; invalid labels: 0; filename overlap: {'train-val': 0, 'train-test': 0, 'val-test': 0}; exact cross-split duplicates: 0.
Perceptual-hash near-duplicates of train (Hamming ≤ 4): val 242, test 71. This source-family overlap pre-dates EAP-1 (noted in CME-OPT2) and is left unchanged so the baseline comparison stays valid; it likely inflates absolute scores.
Training-only augmentation: 1942 degraded copies (one per selected image, seed 42) → 7421 train images. Profiles: {'color_cast_dark': 319, 'uneven_illumination': 325, 'lowlight': 333, 'cctv_compression': 332, 'motion_lowlight': 304, 'synthetic_ir_style': 329}. Val/test contain no training augmentations.
Genuine infrared data: **none available** — real-IR robustness is **NOT VERIFIED**. `synthetic_ir_style` is a grayscale/CLAHE/noise appearance simulation and is never reported as infrared performance.

## Baseline vs candidate (test split; candidate − baseline in percentage points)

| Domain | Images / objects | Baseline P / R / mAP50 / mAP50-95 | Candidate P / R / mAP50 / mAP50-95 | Δ mAP50 | Δ mAP50-95 |
|---|---|---|---|---:|---:|
| Standard validation (selection reference) | 777 / 1334 | 76.83 / 74.23 / 77.25 / 45.66 | 77.85 / 74.67 / 78.67 / 48.38 | +1.43 | +2.73 |
| Standard (original test) | 334 / 498 | 72.80 / 78.02 / 78.17 / 49.19 | 80.99 / 76.23 / 78.96 / 51.68 | +0.79 | +2.49 |
| Natural dark subset (real, luma<80) | 24 / 59 | 55.95 / 80.48 / 70.19 / 38.12 | 63.05 / 72.61 / 77.60 / 42.96 | +7.41 | +4.84 |
| Synthetic low-light | 334 / 498 | 68.72 / 55.35 / 58.62 / 33.93 | 72.60 / 66.20 / 71.43 / 44.21 | +12.81 | +10.28 |
| Synthetic very dark / low contrast | 334 / 498 | 59.62 / 11.19 / 10.50 / 5.23 | 58.00 / 32.86 / 33.09 / 17.92 | +22.59 | +12.70 |
| Synthetic CCTV (blur+JPEG+noise) | 334 / 498 | 71.56 / 46.61 / 52.32 / 31.77 | 66.94 / 56.96 / 59.56 / 36.70 | +7.25 | +4.93 |
| Synthetic IR-style (NOT real IR) | 334 / 498 | 70.00 / 55.79 / 62.07 / 36.30 | 70.97 / 66.10 / 71.36 / 42.88 | +9.30 | +6.58 |

Settings (identical for both): {'imgsz': 640, 'batch': 32, 'conf': 0.001, 'iou': 0.7}; Ultralytics val, split as stated.

## Per-class AP50 (baseline → candidate)

| Class | Standard | Natural dark subset | Synthetic low-light | Synthetic very dark / low contrast | Synthetic CCTV | Synthetic IR-style |
|---|---|---|---|---|---|---|
| baekra | 96.70 → 96.78 | – | 93.18 → 94.47 | 16.25 → 56.26 | 93.55 → 94.55 | 81.95 → 87.69 |
| color issues | 79.59 → 75.93 | – | 68.74 → 80.43 | 7.65 → 55.67 | 72.74 → 67.04 | 55.60 → 64.01 |
| contamination | 96.98 → 97.51 | – | 81.80 → 90.63 | 0.00 → 12.58 | 23.54 → 36.12 | 99.50 → 99.50 |
| cut | 69.02 → 70.75 | – | 58.87 → 70.50 | 8.57 → 40.57 | 53.52 → 57.93 | 68.04 → 68.63 |
| gray stitch | 82.44 → 83.35 | 50.99 → 50.45 | 79.37 → 82.56 | 42.78 → 68.37 | 66.95 → 70.45 | 76.40 → 78.09 |
| selvet | 92.13 → 92.98 | – | 83.57 → 92.44 | 12.35 → 53.28 | 87.61 → 90.77 | 77.46 → 84.90 |
| stain | 92.07 → 93.55 | – | 70.91 → 88.78 | 9.18 → 30.20 | 46.64 → 59.70 | 78.37 → 84.70 |
| chemical hazard (safety) | 42.39 → 53.26 | 49.75 → 99.50 | 24.57 → 37.10 | 0.00 → 1.30 | 26.35 → 28.15 | 46.54 → 43.10 |
| fire (safety) | 63.13 → 59.19 | 76.07 → 70.31 | 20.89 → 40.82 | 0.21 → 5.43 | 38.78 → 46.71 | 8.29 → 30.45 |
| no helmet (safety) | 92.05 → 88.30 | 91.20 → 90.48 | 61.30 → 80.31 | 21.84 → 25.95 | 58.95 → 73.22 | 80.22 → 81.14 |
| smoke (safety) | 54.50 → 67.08 | 70.10 → 82.86 | 17.25 → 43.65 | 4.46 → 11.13 | 19.03 → 37.39 | 31.99 → 57.11 |
| water leak (safety) | 77.04 → 68.89 | 83.00 → 72.00 | 43.04 → 55.54 | 2.72 → 36.34 | 40.12 → 52.75 | 40.46 → 77.03 |

## Regressions (AP50 drop ≥ 5 pp)

- standard: **water leak** 77.04 → 68.89 (-8.15 pp)
- natural_dark: **fire** 76.07 → 70.31 (-5.77 pp)
- natural_dark: **water leak** 83.00 → 72.00 (-11.00 pp)
- synthetic_cctv: **color issues** 72.74 → 67.04 (-5.70 pp)

Low-frequency classes limit confidence: the test split contains only 4 chemical-hazard and 8 water-leak objects; the natural-dark subset is 24 images.

## Acceptance

No EAP-1 numerical mAP target or permitted-regression threshold exists in the task or repository, so no official target is invented. Model performance is therefore **NOT VERIFIED** against an acceptance criterion; the measured deltas above are the evidence for review. The production model (`Backend/best.pt`) is unchanged and remains the fallback.

## Deployment

The candidate `.pt` loads with the same 12-class map through the existing Ultralytics loader used by `Backend/main.py`. It has **not** been exported to ONNX/OpenVINO INT8 or CPU-benchmarked; the existing CME-OPT2 deployment artifacts are untouched and do not correspond to this candidate.

## Definition of done

| Item | Status |
|---|---|
| Repository and Git state preserved | PASS |
| Dataset validation implemented and run | PASS |
| Augmentation pipeline implemented and tested | PASS |
| Baseline evaluated | PASS |
| Fine-tuning completed | PASS |
| Low-light evaluation completed | PASS |
| Genuine IR evaluation completed | NOT VERIFIED - blocked: no annotated genuine infrared data available locally |
| Per-class regression analysis completed | PASS |
| Candidate checkpoint saved and verified | PASS |
| Existing deployment compatibility checked | PASS - .pt loads in existing Ultralytics backend path; ONNX/OpenVINO NOT re-exported |
| OpenVINO/ONNX export revalidated | NOT VERIFIED - candidate not exported; existing CME-OPT2 artifacts untouched |
| Offline requirements verified | PASS |
| Automated tests passed | PASS |
| Documentation and evidence produced | PASS |
| Numerical production acceptance threshold | NOT VERIFIED - undefined for EAP-1 |
| PR created | NOT VERIFIED - deferred: organization repository access revoked; local commits only |

EAP-1 tests: {'collected': 41, 'passed': 41, 'failed': 0, 'skipped': 0, 'error': 0}. Repository tests: {'collected': 480, 'passed': 476, 'failed': 2, 'skipped': 2, 'error': 0}.
