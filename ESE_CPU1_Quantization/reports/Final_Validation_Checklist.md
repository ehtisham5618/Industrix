# ESE-CPU1 Final Validation Checklist

**Overall: FAIL.**

| Requirement | Result | Evidence |
|---|---|---|
| Required Git branch used | PASS | feature/atlantis-openvino-quant |
| Source Backend/best.pt verified as current 12-class model | PASS | Registry checksum,architecture and runtime load test. |
| FP32 baseline evaluated | PASS | Fresh334-image held-out test evaluation. |
| ONNX FP16 exported | PASS | Half-weight graph,ONNX checker and checksums. |
| ONNX FP16 loads in ONNX Runtime | PASS | Actual CPUExecutionProvider session. |
| ONNX FP16 CPU smoke inference works | PASS | Five images plus real runtime unit test and full test evaluation. |
| 300-image calibration set created | PASS | Deterministic seed42 coverage-aware sample. |
| Calibration uses training data only | PASS | Training-path manifest;byte-identical holdout exclusion. |
| Calibration manifest generated | PASS | 300 paths/classes/hashes in calibration_manifest.csv. |
| OpenVINO INT8 PTQ executed with NNCF | PASS | Actual export logs and quantized graph constants. |
| OpenVINO INT8 model loads on CPU | PASS | Runtime load,smoke,NMS and full evaluation. |
| OpenVINO INT8 artifacts saved in required directory | PASS | Backend/weights/openvino_int8/model.xml,model.bin,metadata.yaml. |
| OpenVINO INT8 total model size <6.5 MB | FAIL | XML+BIN=11.773383 decimal MB. |
| FP32 and INT8 evaluated on same test split | PASS | Same sealed334 images/labels and evaluation settings. |
| mAP@50 absolute drop <0.8 pp | FAIL | Drop=1.025515pp. |
| Automated test verifies mAP drop <1.0 pp | FAIL | test_actual_map_drop_below_one_percentage_point;real saved metrics. |
| CPU batch=1 benchmark performed | PASS | Three CPU runtimes;30warmups,200timed calls per category. |
| imgsz=640 used | PASS | Static1x3x640x640;all formats/evaluations. |
| Mean OpenVINO INT8 model inference <20ms | FAIL | Mean=168.299209ms. |
| P95 latency documented | PASS | Full mean/P50/P90/P95/P99/min/max statistics and raw samples. |
| FP32/ONNX/OpenVINO latency comparison documented | PASS | Model-only and end-to-end categories,identical inputs/settings. |
| Per-class AP regression documented | PASS | All12 classes,including chemical,smoke,fire,water leak,no helmet. |
| Benchmark JSON generated | PASS | SED_3_Stress_Testing/reports/quant_report.json. |
| Quantization report generated | PASS | SED_3_Stress_Testing/reports/ESE_CPU1_Quantization_Report.md. |
| Model/deployment registry updated | PASS | Two deployment rows reference the unchanged trained-model registry. |
| CME-3 experiment tracking updated | PASS | 5266e20715bd49b8a577de206c624220 |
| ESE-CPU1 OVERALL | FAIL | All primary accuracy,size and latency gates must pass. |

## Tests and offline delivery

Actual tests: `{'quantization_tests': {'run': 16, 'passed': 14, 'failed': 2, 'errors': 0, 'skipped': 0, 'failures': ['test_quantization.MeasuredQuantizationAcceptance.test_actual_ir_size_below_6_5_decimal_mb', 'test_quantization.MeasuredQuantizationAcceptance.test_actual_map_drop_below_one_percentage_point']}, 'sed3_regression_tests': {'run': 6, 'passed': 6, 'failed': 0, 'errors': 0, 'skipped': 0, 'failures': []}}`.
Size and accuracy acceptance failures are retained as real failing tests; no functional/runtime failures are waived.
Repository access was revoked per user instruction. No push or PR was attempted; no PR URL is asserted.
Exactly two local task commits preserve previous task ancestry. Sync after access returns:

```powershell
git push -u origin feature/atlantis-openvino-quant
```

A verified deployment archive preserves ignored source/optimized binaries. The final verified complete-history Git bundle is in `ESE_CPU1_Quantization/backups/`. Its delivery manifest records both final hashes and checksums. No GPU was allocated; all work was CPU.
