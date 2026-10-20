# EAP-1 — Low-Light & CCTV Infrared Robustness Fine-Tuning

Sprint 3 · Branch `feature/sprint3-eap1-lowlight-ir-robustness` · Task folder
[`EAP_1_LowLight_IR_Robustness/`](../EAP_1_LowLight_IR_Robustness/README.md)

## What changed

- A deterministic (seed 42), geometry-preserving degradation library for
  low light, uneven illumination, CCTV compression/resampling, motion blur,
  colour cast and a clearly labelled *synthetic* IR-style appearance.
- Dataset validation: decodability, YOLO label syntax/class range/box bounds,
  missing labels, exact cross-split duplicates (SHA256) and perceptual-hash
  near-duplicates against train.
- A robustness dataset builder that adds one degraded copy to 35% of training
  images, leaves val/test untouched, and generates fixed synthetic evaluation
  domains from val/test for selection and reporting.
- A Modal A10G worker that verifies the source checkpoint and dataset hashes,
  evaluates the baseline, fine-tunes from the production checkpoint using the
  CME-OPT2 focal-loss trainer, and evaluates the candidate with identical settings.
- Registry entries (`eap1-lowlight-cctv-12class-v1`, `EAP1-EXP-001`) and the
  validator's Sprint 3 / EAP-1 vocabulary.

## What did not change

`Backend/best.pt` remains the production model and fallback. The FastAPI,
Streamlit and OpenVINO/ONNX artifacts are untouched; the candidate is not
exported or CPU-benchmarked and is therefore not deployment-validated.

## Limits of the evidence

- **No genuine infrared or labelled real CCTV night-time data** is available.
  Synthetic domains measure robustness to simulated degradations only.
- The natural-dark subset (real images with mean luma < 80) is small.
- Pre-existing near-duplicate source families between train and val/test
  (see the audit) likely inflate absolute scores for both models equally.
- No numerical acceptance threshold exists for EAP-1, so model performance is
  reported as measured deltas and marked NOT VERIFIED against a target.

Results, per-class tables, regressions and the DoD checklist are in
[`reports/eap1/EAP_1_Low_Light_IR_Robustness_Report.md`](../reports/eap1/EAP_1_Low_Light_IR_Robustness_Report.md).
