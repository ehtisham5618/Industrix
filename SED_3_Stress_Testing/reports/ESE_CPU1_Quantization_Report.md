# ESE-CPU1 Quantization Report

**Overall: FAIL.**

Evidence generated: 2026-10-08T20:14:18.067533+05:00. Original deadline Sep29,2026 was missed; no earlier completion is claimed.

## Source and lineage

CME-OPT1 `combined-12class-v3-hardnegative` -> CME-OPT2 `cme-opt2-focal-cosine-12class-v1` -> `Backend/best.pt` -> versioned ONNX FP16/OpenVINO INT8 deployment formats. Architecture YOLOv8s,12classes,11140244 parameters. Checkpoint SHA256 `c4aba081f6357e23a7370a5f7cf98eff2c6faa0c4c20a2d4dcb8bcabdd490061`. The checkpoint stores compressed floating weights; baseline executes FP32. The trained-model registry and source checkpoint are unchanged. Its previous chemical/smoke target shortfalls remain.
Class names: ['baekra', 'color issues', 'contamination', 'cut', 'gray stitch', 'selvet', 'stain', 'chemical hazard', 'fire', 'no helmet', 'smoke', 'water leak']. Actual portable YAML: `Hazard_Expansion/configs/12class_data.yaml`, existing augmented_v3 train/val/test paths.

## Environment

Actual environment: `{'python': '3.12.9', 'os': 'Windows-11-10.0.26200-SP0', 'cpu': 'Intel(R) Core(TM) i5-7200U CPU @ 2.50GHz', 'is_intel': True, 'physical_cores': 2, 'logical_cores': 4, 'ram_bytes': 17049018368, 'packages': {'ultralytics': '8.4.24', 'torch': '2.10.0', 'onnx': '1.23.2', 'onnxruntime': '1.24.4', 'openvino': '2026.4.1', 'nncf': '3.4.0', 'numpy': '2.4.6', 'mlflow': '2.22.2'}, 'cpu_load_percent_at_snapshot': 45.9, 'system_load_note': 'Shared user workstation; no exclusive machine isolation claimed.'}`. CPU execution only; no GPU/NPU provider was used. The workstation is shared, not exclusively isolated.

## Calibration and export

{'count': 300, 'seed': 42, 'strategy': 'Seeded greedy inverse-current-image-class-coverage; training only', 'image_class_coverage': {'baekra': 29, 'color issues': 29, 'contamination': 29, 'cut': 29, 'gray stitch': 29, 'selvet': 29, 'stain': 29, 'chemical hazard': 29, 'fire': 63, 'no helmet': 38, 'smoke': 53, 'water leak': 28}, 'byte_identical_holdout_images_excluded': 0, 'dataset_version': 'combined-12class-v3-hardnegative', 'manifest_sha256': '31bfc86e6eeefd2c07ee14cf444fbcbc417f09f83d758e2be053797701a0c23f'}. Exactly300 training images,seed42,greedy inverse-current-class-coverage selection. Byte-identical holdout images are excluded. [Manifest](../../ESE_CPU1_Quantization/reports/calibration_manifest.csv) includes paths,class IDs,andSHA256. Calibration is distinct from val selection and test evaluation.
PTQ attempts: `{'attempts': [{'attempt': 1, 'type': 'standard_nncf_ptq', 'selection_split': 'val', 'drop_pp': -0.1208191042198159, 'relative_change_pct': 0.15911346689931147, 'strict_0_8pp_pass': True, 'dod_1_0pp_pass': True}, {'attempt': 2, 'type': 'nncf_accuracy_control', 'selection_split': 'val', 'trigger': 'strict held-out target shortfall', 'max_drop': 0.0079, 'drop_pp': -0.3622068021354452, 'relative_change_pct': 0.47701048931325574, 'strict_0_8pp_pass': True, 'dod_1_0pp_pass': True}], 'selected': 'accuracy_aware', 'test_not_used_for_selection': True}`. Ultralytics 8.4.24 supports int8/half, not quantize8/16. Exactly 300 training paths, fraction1.0, split=train. Actual NNCF activation FakeQuantize ops=67; constant bytes by precision={"<Type: 'int64_t'>": 400, "<Type: 'float32'>": 183848, "<Type: 'int8_t'>": 11119984, "<Type: 'int32_t'>": 44}. The standard export keeps the upstream detection-head ignored scope and MIXED preset. [NNCF API](https://openvinotoolkit.github.io/nncf/autoapi/nncf/) describes accuracy control. Here the strict held-out shortfall triggered its investigation; validation data alone calibrated the comparison and selected the resulting candidate. Test images never calibrated or ranked scopes.
ONNX FP16 uses CPU FP32 export then onnxconverter-common conversion with FP32 IO; FP16 weights are verified and ONNX checker/CPU session smoke tests execute. CPU provider may promote unsupported half kernels; this does not claim native FP16 CPU arithmetic. See [ORT float16 documentation](https://onnxruntime.ai/docs/performance/model-optimizations/float16.html). Both deployment formats return batch1,16channels,8400candidates (4box+12class scores). Five representative training smoke images and full held-out evaluation validate finite outputs; benchmark NMS validates class IDs.

## Artifact sizes

| Artifact | Bytes | Decimal MB |
|---|---:|---:|
| PyTorch source checkpoint | 22498282 | 22.498282 |
| onnx_fp16 | 22409010 | 22.409010 |
| openvino_xml | 470147 | 0.470147 |
| openvino_bin | 11303236 | 11.303236 |
| metadata | 659 | 0.000659 |
| OpenVINO XML+BIN | 11773383 | 11.773383 |

Primary size gate uses combined XML+BIN <6,500,000bytes: **FAIL**. MiB=11.227973; runtime metadata is separately counted; complete runtime bytes=11774042. No files were deleted to shrink the reported model. Artifact SHA256 values and storage paths are in the manifest. Genuine INT8 of this11.1Mparameter model can exceed6.5MB; no smaller architecture/retraining/int4 substitution is presented as the required model.

## Held-out accuracy

Same334 test images,labels,and sealed manifest for all formats;imgsz640,batch1,rectFalse,conf0.001,iou0.7,max_det300. CME-2 alert thresholds are not used for mAP. Source baseline is newly evaluated,not copied from old reports.

| Metric | PyTorch FP32 | OpenVINO INT8 | INT8 minus FP32 pp | ONNX FP16 |
|---|---:|---:|---:|---:|
| precision | 76.880718% | 75.508787% | -1.371931 | 76.802094% |
| recall | 77.605770% | 76.517833% | -1.087937 | 77.595690% |
| map50 | 77.862826% | 76.837312% | -1.025515 | 77.853754% |
| map50_95 | 49.242194% | 49.311512% | 0.069319 | 49.257623% |

mAP50 drop=1.025515percentage points; relative change=-1.317079%. Strict<0.8pp: **FAIL**; automated<1.0pp: **FAIL**.

| Class | FP32 AP50% | INT8 AP50% | INT8 minus FP32 pp |
|---|---:|---:|---:|
| baekra | 96.700000 | 95.697802 | -1.002198 |
| color issues | 75.112770 | 76.342534 | 1.229764 |
| contamination | 93.393750 | 90.335929 | -3.057821 |
| cut | 68.176973 | 66.952949 | -1.224024 |
| gray stitch | 76.849264 | 74.269721 | -2.579543 |
| selvet | 90.199656 | 90.101938 | -0.097718 |
| stain | 91.214117 | 89.956583 | -1.257534 |
| chemical hazard | 41.513433 | 41.551853 | 0.038420 |
| fire | 62.268947 | 61.185885 | -1.083062 |
| no helmet | 88.180235 | 87.597320 | -0.582915 |
| smoke | 51.244771 | 50.955226 | -0.289545 |
| water leak | 99.500000 | 97.100000 | -2.400000 |

## CPU latency methodology

Settings: `{'onnx_providers': ['CPUExecutionProvider'], 'onnx_intra_op': 2, 'onnx_inter_op': 1, 'openvino_device': 'CPU', 'openvino_performance_hint': 'LATENCY', 'openvino_streams': 1, 'openvino_threads': 2, 'openvino_execution_devices': ['CPU'], 'pytorch_threads': 2, 'pytorch_interop_threads': 1, 'compile_seconds': 1.3284689000574872}`. Model-only: `Preprocessed float32 batch1 tensor; synchronous runtime call, outputs materialized; inference_mode`. End-to-end: `In-memory JPEG/PNG decode,letterbox640,RGB normalization,runtime,NMS; excludes disk IO and tracker/alerts`. Same five held-out input images per runtime;30warmup/200timed calls per category; all samples retained. Compilation is reported separately. Settings/static640x640/batch1/CPU remain identical; no lowered resolution,minimum-only statistic or selected removal of slow runs.

| Backend / category | Mean ms | P50 | P90 | P95 | P99 | Min | Max |
|---|---:|---:|---:|---:|---:|---:|---:|
| fp32_cpu / model | 371.738737 | 350.304400 | 435.657100 | 489.533200 | 570.820600 | 301.760000 | 1522.902900 |
| onnx_fp16_cpu / model | 282.847687 | 262.213900 | 340.069500 | 393.275400 | 489.387300 | 239.647900 | 579.606500 |
| openvino_int8_cpu / model | 168.299209 | 131.626700 | 225.119400 | 299.404900 | 647.970200 | 124.815300 | 1431.815900 |
| fp32_cpu / end-to-end | 378.084561 | 359.391900 | 437.972200 | 502.338200 | 585.534400 | 314.370500 | 691.098400 |
| onnx_fp16_cpu / end-to-end | 342.685180 | 329.397000 | 396.832500 | 429.057600 | 518.967600 | 264.405000 | 658.823800 |
| openvino_int8_cpu / end-to-end | 231.325141 | 215.246200 | 257.808100 | 294.186000 | 478.883300 | 204.387400 | 671.953000 |

OpenVINO mean model inference<20ms: **FAIL**. Speedup versus PyTorch=2.208797x. P95 is separately reported. A hardware-specific performance shortfall remains visible; it is not relabeled as full-pipeline latency or throughput.

## Tests, tracking and delivery

Test results: `{'quantization_tests': {'run': 16, 'passed': 14, 'failed': 2, 'errors': 0, 'skipped': 0, 'failures': ['test_quantization.MeasuredQuantizationAcceptance.test_actual_ir_size_below_6_5_decimal_mb', 'test_quantization.MeasuredQuantizationAcceptance.test_actual_map_drop_below_one_percentage_point']}, 'sed3_regression_tests': {'run': 6, 'passed': 6, 'failed': 0, 'errors': 0, 'skipped': 0, 'failures': []}}`. The real saved-metric test is `test_actual_map_drop_below_one_percentage_point`; the real XML+BIN size test is `test_actual_ir_size_below_6_5_decimal_mb`. Functional/runtime failures are never accepted as numeric shortfalls.
CME-3 experiment `ESECPU1-EXP-001`; actual MLflow run `5266e20715bd49b8a577de206c624220` via the existing helper and `Vision-Driven-Industrial-Safety` experiment name. This offline task creates the local project filesystem store `Experiment_Tracking/mlruns`; historical Modal runs remain unchanged. Source trained-model history stays unchanged; two deployment rows reference `cme-opt2-focal-cosine-12class-v1`. Registry files are append-only.
Branch `feature/atlantis-openvino-quant`; exactly two local task commits. Push and PR creation are deferred because organization access was revoked; no PR URL is invented. Run `git push -u origin feature/atlantis-openvino-quant` when permission returns. A verified Git bundle and separate binary archive preserve both source history and artifacts.

## Deployment recommendation

Keep the current production default until the measured acceptance gates are met on approved deployment hardware. Generated formats are validated deployment candidates; they do not establish that the source detector meets its previous hazard-class or temporal-recall targets. The current results and all unmet gates are explicit in the checklist.

[Full acceptance checklist](../../ESE_CPU1_Quantization/reports/Final_Validation_Checklist.md); [artifact manifest](../../ESE_CPU1_Quantization/reports/artifact_manifest.json); [raw latency samples](../../ESE_CPU1_Quantization/reports/latency_samples.csv).

## Preserved basic PTQ attempt

Attempt1 basic PTQ test mAP50=76.939515%, drop=0.923312pp; core size=11.771971MB; mean CPU model latency=136.895076ms; status=FAIL. The complete first result and raw latency samples are retained. The strict test shortfall triggers a validation-only accuracy-control investigation; the test images never calibrate or rank/restores scopes.
[First measured attempt](../../ESE_CPU1_Quantization/reports/basic_ptq_quant_report.json). Current selected result and both validation attempts are reported above. Percentiles use the existing SED-3 nearest-rank convention. No source training,lowered resolution or adjusted acceptance threshold was used.

## Review artifacts

[Deployment size and CPU latency graph](../../ESE_CPU1_Quantization/reports/cpu_deployment_comparison.png); [per-class AP change graph](../../ESE_CPU1_Quantization/reports/per_class_quantization_delta.png); [created/modified/generated file inventory](../../ESE_CPU1_Quantization/reports/file_inventory.json).

OpenVINO runtime node precision tags: `{'f32': 160, 'i32': 94, 'u8': 98, 'i8': 64}`. These are node counts, not fractions of execution time. All execution devices are CPU.
