# EAP-1 — Low-light & CCTV infrared robustness fine-tuning

Sprint 3. Fine-tunes the production 12-class YOLOv8s detector
(`Backend/best.pt`, `cme-opt2-focal-cosine-12class-v1`, SHA256 `c4aba081…0061`)
for dark, unevenly lit, noisy, blurred and compressed CCTV imagery, and compares
it against that unchanged baseline on identical evaluation sets.

Review report: [`reports/eap1/EAP_1_Low_Light_IR_Robustness_Report.md`](../reports/eap1/EAP_1_Low_Light_IR_Robustness_Report.md)
Machine-readable summary: [`reports/eap1/eap1_robustness_summary.json`](../reports/eap1/eap1_robustness_summary.json)

## Data reality

- Source: CME-OPT1 `combined-12class-v3-hardnegative` (5479 / 777 / 334 images),
  the same archive CME-OPT2 trained on (SHA256 verified before use).
- **No genuine infrared/thermal or labelled CCTV night-time detection data exists**
  in the repository or local data locations. Real-IR robustness is therefore
  **NOT VERIFIED**. `synthetic_ir_style` (red-weighted grayscale + CLAHE + noise)
  is an appearance simulation, kept as a separately named domain and never
  reported as infrared performance.
- `natural_dark` is the only real low-light evidence: unmodified val/test images
  whose mean luma is below 80 (small; see report counts).
- To add genuine IR later, a source must provide bounding boxes for these 12
  classes (or a documented subset) under a compatible licence; place it as a new
  YOLO domain and add it to `evaluation.domains`. Unrelated IR labels (e.g.
  pedestrians/cars) must not be remapped into defect/hazard classes.

## Pipeline

| File | Purpose |
|---|---|
| `configs/eap1_lowlight.yaml` | Seed, source hashes, augmentation, evaluation and training config |
| `degradations.py` | Deterministic geometry-preserving low-light/CCTV/IR-style transforms |
| `dataset_tools.py` | Image/label/split validation, near-duplicate audit, robustness dataset builder |
| `evaluate.py` | Identical-settings Ultralytics evaluation, report validation, deltas |
| `pipeline.py` | Worker: verify inputs → build → baseline eval → fine-tune → candidate eval |
| `modal_runner.py` | A10G execution on Modal with cost controls |
| `local_audit.py` | Offline full-dataset audit and augmentation contact sheet |
| `finish_evidence.py` | Summary JSON + review report from fetched artifacts only |
| `register_experiment.py` | Appends the measured run to the existing CSV registries |

Training-only augmentation: 35% of train images (deterministic, seed 42) get
**one** degraded copy each (six profiles), so no image is stacked with
near-identical variants. Val and test are untouched. Fixed synthetic evaluation
domains are generated from the val/test bytes; the val domains plus original
val form the checkpoint-selection set, the test domains are evaluated once
after training. Labels are copied unchanged because every transform preserves
geometry (tested).

Fine-tuning reuses the CME-OPT2 focal-loss trainer and class gain (`cls=2.0`)
from the source checkpoint's own lineage. Both prior CME-OPT2 fine-tunes from
this lineage peaked at epoch 1 with `lr0` 0.01/0.001 and warmup, so EAP-1 uses
SGD `lr0=0.002`, no warmup, cosine to `lrf=0.1`, 10 epochs, patience 4.

## Reproduce

```powershell
$env:PYTHONIOENCODING = 'utf-8'
python -X utf8 EAP_1_LowLight_IR_Robustness/local_audit.py
python -X utf8 -m modal run --detach EAP_1_LowLight_IR_Robustness/modal_runner.py
python -m modal volume get industirx-eap1 reports reports/eap1/remote
python -m modal volume get industirx-eap1 runs/eap1_lowlight_v1/weights/best.pt EAP_1_LowLight_IR_Robustness/runtime/eap1_lowlight_v1/best.pt
python -X utf8 EAP_1_LowLight_IR_Robustness/finish_evidence.py
python -X utf8 -m pytest EAP_1_LowLight_IR_Robustness/tests -q
```

GPU cost controls: zero minimum containers, 60 s scale-down after the call
returns, a 3000 s hard timeout, and the CME-OPT2 watchdog that terminates the
worker after 600 continuous seconds at 0% GPU utilization. Stop the app
explicitly afterwards with `python -m modal app stop --yes <APP_ID>`.

Checkpoints and datasets are git-ignored. The candidate is stored on the Modal
volume `industirx-eap1` and locally under `runtime/`; verify it with the SHA256
in the summary JSON before use. The production model is not replaced.
