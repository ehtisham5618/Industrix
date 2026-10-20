# EAP-1: improve industrial detector low-light robustness

Fine-tunes the production 12-class YOLOv8s (`Backend/best.pt`, SHA256 `c4aba081…0061`,
unchanged) with deterministic training-only low-light, uneven-illumination, CCTV
compression, motion-blur, colour-cast and synthetic IR-style degradations
(1942 extra images, one per selected train image). Selection used validation
only (original + fixed synthetic val domains); test domains were evaluated once.

Measured on identical test sets (candidate − baseline, mAP50-95 pp): standard
+2.49, natural-dark real subset (24 images) +4.84, synthetic low-light +10.28,
synthetic very dark +12.70, synthetic CCTV +4.93, synthetic IR-style +6.58.
AP50 regressions ≥5 pp: water leak on standard (−8.15, 8 objects), fire/water
leak on the 24-image natural-dark subset, colour issues on synthetic CCTV.

Not verified: genuine infrared performance (no annotated IR data exists),
numerical acceptance threshold (undefined for EAP-1), ONNX/OpenVINO export and
CPU benchmark of the candidate. Production model remains the fallback.

Tests: EAP-1 41/41 pass; repository 476 pass / 2 skipped / 2 inherited CPU1
gate failures. Registry validation PASS. Report:
`reports/eap1/EAP_1_Low_Light_IR_Robustness_Report.md`.
This body is prepared locally; no PR has been opened (repository access revoked).
