# ESE-CPU3 Soak Test Report

**Execution: completed; acceptance: FAIL.**

Actual UTC start 2026-10-08T16:38:56.852982+00:00, finish 2026-10-08T16:40:14.885524+00:00. Original October 1 deadline has passed; no earlier completion is claimed.

## System and methodology

Detector `cme-opt2-focal-cosine-12class-v1` → CPU1 selected OpenVINO INT8 → CPU2 independent captures/ring15/sample4 → CME-OPT3 calibrated ByteTRACK/15 evaluated observations → SED-2 software-only escalation. Config `ESECPU3-soak60-v1` / `ESECPU2-async-ring15-sample4-v1`. Exact class mapping, hashes, precision, compilation and CPU settings: `{'device': 'CPU', 'execution_devices': ['CPU'], 'input_shape': [1, 3, 640, 640], 'output_shape': [1, 16, 8400], 'class_names': {0: 'baekra', 1: 'color issues', 2: 'contamination', 3: 'cut', 4: 'gray stitch', 5: 'selvet', 6: 'stain', 7: 'chemical hazard', 8: 'fire', 9: 'no helmet', 10: 'smoke', 11: 'water leak'}, 'artifact_manifest': {'source_model_version': 'cme-opt2-focal-cosine-12class-v1', 'source_sha256': 'c4aba081f6357e23a7370a5f7cf98eff2c6faa0c4c20a2d4dcb8bcabdd490061', 'dataset_version': 'combined-12class-v3-hardnegative', 'artifacts': {'onnx_fp16': {'path': 'Backend/weights/onnx_fp16/best_fp16.onnx', 'bytes': 22409010, 'sha256': '076395d62f8af1e386891de20ae0c0b417938346bfd90a922f8ece92afefdddf'}, 'openvino_xml': {'path': 'Backend/weights/openvino_int8/model.xml', 'bytes': 470147, 'sha256': '3f47534f9f4c1f7ae69979e311a91c89decff27034e9d3a71c2af70c01c1d40a'}, 'openvino_bin': {'path': 'Backend/weights/openvino_int8/model.bin', 'bytes': 11303236, 'sha256': 'ec2d1de0ac55791c88f12f3f501bf1f97e01218270486557051c3256481359aa'}, 'metadata': {'path': 'Backend/weights/openvino_int8/metadata.yaml', 'bytes': 659, 'sha256': 'f8245629ade1077bcff9c960a025459c4e8683910a1fd82c05868cddf2d2a96a'}}, 'combined_core_bytes': 11773383, 'combined_core_decimal_mb': 11.773383, 'combined_core_mib': 11.227972984313965, 'required_metadata_bytes': 659, 'complete_runtime_bytes': 11774042, 'size_target_bytes': 6500000, 'size_pass': False, 'nncf_fake_quantize_ops': 67, 'constant_bytes_by_precision': {"<Type: 'int64_t'>": 400, "<Type: 'float32'>": 183848, "<Type: 'int8_t'>": 11119984, "<Type: 'int32_t'>": 44}, 'export_api': 'Ultralytics8.4.24 FP32 OpenVINO conversion; NNCF quantize_with_accuracy_control; absolute max_drop0.0079;targetCPU;MIXED;exactly300 training samples', 'detection_head_policy': 'Unmodified upstream ignored Add/Sub/Mul/Div detection-head patterns and Sigmoid; MIXED preset', 'onnx_fp16_policy': 'CPU FP32 ONNX export, onnxconverter-common FP16 conversion with FP32 IO; CPU EP may promote unsupported kernels', 'versions': {'ultralytics': '8.4.24', 'torch': '2.10.0', 'onnx': '1.23.2', 'onnxruntime': '1.24.4', 'openvino': '2026.4.1', 'nncf': '3.4.0', 'numpy': '2.4.6', 'mlflow': '2.22.2'}, 'selected_ptq': 'accuracy_aware'}, 'runtime_precision_counts': {'f32': 160, 'i32': 94, 'u8': 98, 'i8': 64}, 'openvino_version': '2026.4.1-22982-e213a147257-releases/2026/4', 'settings': {'performance_hint': 'LATENCY', 'num_streams': 1, 'threads': 2}, 'compilation_seconds': 0.8258355000289157}`.
Hardware/software: `{'cpu': 'Intel(R) Core(TM) i5-7200U CPU @ 2.50GHz', 'physical_cores': 2, 'logical_cores': 4, 'ram_bytes': 17049018368, 'os': 'Windows-11-10.0.26200-SP0', 'python': '3.12.9 (tags/v3.12.9:fdb8142, Feb  4 2025, 15:27:58) [MSC v.1942 64 bit (AMD64)]', 'openvino': '2026.4.1-22982-e213a147257-releases/2026/4', 'opencv': '5.0.0', 'psutil': '7.2.2'}`. Requested monitored soak 60.0s; actual 60.059s. Warmup 15.0s runs in the same process before the primary monitored period. Capture wall 75.059s; with shutdown 78.030s. No pipeline restart on media looping. Tracemalloc begins before warmup; post-warmup analysis excludes warmup. Sampling interval 1s; full telemetry persisted rather than retained in an accumulating Python list.
CPU1 deployment targets previously failed. This task exercises its selected artifact without promoting it or overriding that acceptance. No retraining, quantization rerun, resolution change, GPU/NPU or fallback backend. Input static batch1 640x640, CPU LATENCY/one stream/two threads as validated by CPU1. A shared scheduler may select three frames; the static artifact runs each once in order, then real NMS rescales boxes to source coordinates before tracking/geofences. Pure model latency excludes preprocessing/NMS; separate timers record those and tracking/escalation routing. No dummy detector.
The host is shared, not exclusively isolated. Tracemalloc adds measured instrumentation overhead. One-hour claims apply only to this workstation and configuration. Temperature is unavailable unless the host exposes a supported CPU sensor; frequency on Windows can be nominal and cannot independently establish thermal throttling.

## Feeds and throughput

Three nominal 30 FPS feeds sampled 1-in-4 cap operational FPS at 22.5; these native-rate feeds cap it at 19.7305. Neither cap reaches 45. The sampler remains enabled.
Operational integrated FPS **2.747**; separately measured ready-tensor engine capacity **None FPS**. The 45 FPS operational gate is **FAIL**. Engine capacity also fails 45 FPS. Capacity never substitutes for camera throughput. Frame completion timestamps during the 3600-second period define throughput; stop drain is excluded. All raw sampler skips and true selected-frame overruns remain separately counted. Actual RTSP test NOT RUN.
| Camera | Source | Source FPS | Soak eval FPS | Captured total | Evaluated total | Skips | True overruns | Rewinds |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| camera_01: Fabric Weaving Feed | data/test_factory_clip.mp4 | 25.000 | 0.916 | 1877 | 72 | 1407 | 398 | 0 |
| camera_02: Chemical Storage Bay | Confidence_Calibration/benchmark/media/chemical_hazard_01_hazmat_training.webm | 29.946 | 0.916 | 2248 | 70 | 1686 | 492 | 1 |
| camera_03: Loading Bay | Confidence_Calibration/benchmark/media/no_helmet_01_workers_roof.webm | 23.976 | 0.916 | 1799 | 71 | 1349 | 379 | 3 |

Source roles use public documentary/hazmat-exercise/rooftop-worker simulations. These are not installed weaving/chemical/loading-bay CCTV; original media provenance remains in CPU2/CME-OPT3 reports. Source hashes and native dimensions are in JSON. RTP network losses are not observable through OpenCV.

## Latency, CPU and memory

Pure OpenVINO latency milliseconds: `{'mean_ms': 353.3983539393939, 'p50_ms': 243.35, 'p95_ms': 834.2312, 'p99_ms': 1164.5143, 'min_ms': 159.7333, 'max_ms': 1348.0123}`. Separate preprocessing, NMS, tracking/escalation routing and capture-to-completion: `{'preprocess_ms': {'mean': 7.22835393939394, 'p50': 7.0284, 'p95': 10.8464, 'p99': 16.1449, 'min': 4.5921, 'max': 17.0944}, 'nms_ms': {'mean': 1.9499896969696968, 'p50': 1.2525, 'p95': 4.9641, 'p99': 13.8074, 'min': 0.7393, 'max': 25.5462}, 'routing_ms': {'mean': 2.7677781809347146, 'p50': 2.239400055259466, 'p95': 7.945899968035519, 'p99': 14.568799990229309, 'min': 0.13219995889812708, 'max': 15.503700007684529}, 'end_to_end_ms': {'mean': 1579.3647848365997, 'p50': 1471.9003000063822, 'p95': 2578.908700030297, 'p99': 3051.1780000524595, 'min': 990.3306999476627, 'max': 3067.5554999615997}}`. All measured calls, not the last bounded diagnostic cache, determine percentiles. Stop drain is excluded.
CPU: `{'process_mean_pct': 46.37875, 'process_p95_pct': 57.975, 'process_peak_pct': 60.55, 'system_mean_pct': 87.34333333333333, 'system_peak_pct': 100.0, 'process_normalized': {'mean': 46.37875, 'p50': 46.875, 'p95': 57.975, 'p99': 60.55, 'min': 25.4, 'max': 60.55}, 'process_raw': {'mean': 185.515, 'p50': 187.5, 'p95': 231.9, 'p99': 242.2, 'min': 101.6, 'max': 242.2}, 'system': {'mean': 87.34333333333333, 'p50': 86.0, 'p95': 100.0, 'p99': 100.0, 'min': 70.5, 'max': 100.0}, 'normalization': 'Process CPU divided by four logical CPUs; machine normalized 0-100%, raw percent also retained'}`. Raw process CPU can exceed 100%; machine normalized process CPU divides by four logical cores. Both percent series remain available.
Memory: `{'rss_start_mb': 554.2421875, 'rss_mean_mb': 560.5889973958333, 'rss_peak_mb': 571.234375, 'rss_end_mb': 564.68359375, 'rss_slope_mb_per_hour': 354.0533690608904, 'tracemalloc_start_mb': 149.69797706604004, 'tracemalloc_peak_mb': 168.9335699081421, 'tracemalloc_end_mb': 149.81135654449463, 'leak_detected': False, 'analysis': {'process_rss_mb': {'leak_detected': False, 'evidence_sufficient': True, 'slope_mb_per_hour': 354.0533690608904, 'final_twenty_minute_slope_mb_per_hour': 566.3844687764388, 'early_window_mean_mb': 558.5671875, 'final_window_mean_mb': 563.3875, 'window_growth_mb': 4.8203125, 'material_growth_threshold_mb': 27.928359375000003, 'slope_threshold_mb_per_hour': 11.171343750000002, 'reason': 'No sustained material upward trend supported by all indicators; bounded cache/history fill is allowed'}, 'tracemalloc_current_mb': {'leak_detected': False, 'evidence_sufficient': True, 'slope_mb_per_hour': 4.196800156599361, 'final_twenty_minute_slope_mb_per_hour': 120.86684506328656, 'early_window_mean_mb': 149.5421692530314, 'final_window_mean_mb': 149.83716570536296, 'window_growth_mb': 0.29499645233156, 'material_growth_threshold_mb': 7.477108462651571, 'slope_threshold_mb_per_hour': 2.990843385060628, 'reason': 'No sustained material upward trend supported by all indicators; bounded cache/history fill is allowed'}}, 'system_ram': {'mean': 72.86833333333334, 'p50': 73.0, 'p95': 73.2, 'p99': 73.5, 'min': 72.3, 'max': 73.5}, 'conclusion': 'Full-duration leak conclusion unavailable for incomplete/short run'}`. Units MiB (2^20 bytes). RSS covers native memory that Python tracing may miss. Python allocation peak and end are independently captured; slight allocator/cache fluctuation alone does not imply a leak.
Memory heuristic: after warmup, require a materially positive whole-run slope, first-to-final stable-window increase, AND a materially positive final-20-minute slope before flagging sustained growth. RSS minimum material growth is 10 MiB and Python minimum 1 MiB; relative growth threshold is 5% of early-window memory and slope threshold at least 2%/hour. These thresholds were defined before measurement. Fixed history/cache filling that plateaus is distinguished from continuing growth. Top ten positive allocation deltas are saved at 15/30/45/60 minutes. This is evidence for a finite one-hour run, not proof that every possible workload is leak-free.
Memory conclusion: **Full-duration leak conclusion unavailable for incomplete/short run**.

## Thermal and reliability

Thermal/frequency report: `{'temperature_available': False, 'frequency_available': True, 'temperature': None, 'frequency': {'mean': 2511.0, 'p50': 2511.0, 'p95': 2511.0, 'p99': 2511.0, 'min': 2511.0, 'max': 2511.0}, 'mean_temp_c': None, 'peak_temp_c': None, 'mean_freq_mhz': 2511.0, 'min_freq_mhz': 2511.0, 'throttling_detected': None, 'throttling_evidence': 'Unable to determine due to unavailable telemetry: no exposed CPU thermal-limit or OS throttling counter. Frequency variation alone is not evidence of thermal throttling.', 'frequency_source': 'psutil.cpu_freq; on Windows reported frequency may be nominal and is not a per-core real-time thermal counter'}`. Missing metrics are null/blank, never fabricated zeros. Frequency change alone is not labeled throttling.
Health: `{'crashes': 0, 'reconnects': 0, 'read_failures': 0, 'buffer_overruns': 1269, 'capture_threads_stable': True, 'native_threads_min': 37.0, 'native_threads_max': 40.0, 'ring_capacity_bounded': True, 'clean_shutdown': True}`. Thread counts `{'before': 15, 'before_shutdown': 37, 'after_shutdown': 12}`; active capture workers after stop `[]`. Event histories/resolved records are bounded to 1024 in this harness and archived to the existing JSONL event store; active safety incidents are never evicted. CPU2 rings remain 15 slots, timing diagnostic histories remain 4096 entries, and per-frame timing records are streamed to disk. Alert storage: `{'retention_limit': 1024, 'retained_events': 0, 'archived_events': 0, 'log_bytes': 0}`.
Failures: `[]`. All three streams loop independently; loop sessions reset tracking/escalation according to CPU2 behavior without restarting the process, clock or telemetry.

## Six 10-minute windows

| Window | FPS | Mean inference ms | P95 ms | System CPU % | RSS MiB | Python MiB | Temp C | MHz |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0-10 min | 2.720 | 353.398 | 834.231 | 87.343 | 560.589 | 149.605 | NA | 2511.000 |

Early/final window comparison: `None`. Workload, source clips, runtime settings and sampling remain unchanged. Performance variation is retained and not used to invent a thermal diagnosis.

## Definition of Done

| Check | Result |
|---|---|
| Required Git branch used | PASS |
| OpenVINO INT8 engine verified | PASS |
| 3 concurrent simulated feeds active | PASS |
| ESE-CPU2 async ingestion reused | PASS |
| 60-minute / 3600-second continuous run completed | FAIL |
| No unrecoverable crashes | PASS |
| Process RSS monitored | PASS |
| tracemalloc monitored | PASS |
| No evidence of sustained RSS growth | FAIL |
| No evidence of sustained Python allocation growth | FAIL |
| Thread/worker count stable | PASS |
| Ring buffers stable | PASS |
| CPU utilization recorded | PASS |
| CPU frequency recorded | PASS |
| CPU temperature recorded | UNAVAILABLE |
| Thermal throttling analyzed | UNAVAILABLE |
| Operational aggregate FPS documented | PASS |
| Inference-capacity FPS documented where required | FAIL |
| >=45 FPS task target | FAIL |
| Latency mean/P95/P99 documented | PASS |
| cpu_soak_report.json generated | PASS |
| CPU/RAM telemetry graphs generated | PASS |
| Final soak report generated | PASS |
| CME-3 tracking updated | PENDING until offline finalization |
| ESE-CPU3 OVERALL | FAIL |

## Artifacts and offline delivery

JSON `SED_3_Stress_Testing/reports/cpu_soak_smoke_report.json`, telemetry `SED_3_Stress_Testing/reports/cpu_soak_smoke_timeseries.csv`, inference timing `SED_3_Stress_Testing/reports/cpu_soak_smoke_inference.csv`, frame timing `SED_3_Stress_Testing/reports/cpu_soak_smoke_frames.csv`. CPU, memory, FPS and frequency graphs use only measured samples. Tests and CME-3 run metadata are attached during finalization after the real full-duration evidence exists.
Required feature branch `feature/atlantis-cpu-soak-test` is based on completed local CPU2. Exactly two task commits are saved after actual 60-minute evidence; user reports organization access revoked, so no push/PR now. Later sync: `git push -u origin feature/atlantis-cpu-soak-test`. Verified Git bundle, artifact/media archive and local tracking archive remain ignored under `ESE_CPU3_Soak_Test/backups/`.

[CPU graph](cpu_soak_smoke_cpu.png), [memory graph](cpu_soak_smoke_memory.png), [throughput graph](cpu_soak_smoke_fps.png), [frequency graph](cpu_soak_smoke_thermal.png).

References: [OpenVINO CPU properties](https://docs.openvino.ai/nightly/openvino-workflow/running-inference/inference-devices-and-modes/cpu-device.html), [tracemalloc limits and snapshots](https://docs.python.org/3/library/tracemalloc.html), [psutil frequency and sensors](https://psutil.readthedocs.io/stable/index.html).
