# ESE-CPU3 Soak Test Report

**Execution: completed; acceptance: FAIL.**

Actual UTC start 2026-10-08T16:45:23.020009+00:00, finish 2026-10-08T17:46:26.178552+00:00. Original October 1 deadline has passed; no earlier completion is claimed.

## System and methodology

Detector `cme-opt2-focal-cosine-12class-v1` → CPU1 selected OpenVINO INT8 → CPU2 independent captures/ring15/sample4 → CME-OPT3 calibrated ByteTRACK/15 evaluated observations → SED-2 software-only escalation. Config `ESECPU3-soak60-v1` / `ESECPU2-async-ring15-sample4-v1`. Exact class mapping, hashes, precision, compilation and CPU settings: `{'device': 'CPU', 'execution_devices': ['CPU'], 'input_shape': [1, 3, 640, 640], 'output_shape': [1, 16, 8400], 'class_names': {0: 'baekra', 1: 'color issues', 2: 'contamination', 3: 'cut', 4: 'gray stitch', 5: 'selvet', 6: 'stain', 7: 'chemical hazard', 8: 'fire', 9: 'no helmet', 10: 'smoke', 11: 'water leak'}, 'artifact_manifest': {'source_model_version': 'cme-opt2-focal-cosine-12class-v1', 'source_sha256': 'c4aba081f6357e23a7370a5f7cf98eff2c6faa0c4c20a2d4dcb8bcabdd490061', 'dataset_version': 'combined-12class-v3-hardnegative', 'artifacts': {'onnx_fp16': {'path': 'Backend/weights/onnx_fp16/best_fp16.onnx', 'bytes': 22409010, 'sha256': '076395d62f8af1e386891de20ae0c0b417938346bfd90a922f8ece92afefdddf'}, 'openvino_xml': {'path': 'Backend/weights/openvino_int8/model.xml', 'bytes': 470147, 'sha256': '3f47534f9f4c1f7ae69979e311a91c89decff27034e9d3a71c2af70c01c1d40a'}, 'openvino_bin': {'path': 'Backend/weights/openvino_int8/model.bin', 'bytes': 11303236, 'sha256': 'ec2d1de0ac55791c88f12f3f501bf1f97e01218270486557051c3256481359aa'}, 'metadata': {'path': 'Backend/weights/openvino_int8/metadata.yaml', 'bytes': 659, 'sha256': 'f8245629ade1077bcff9c960a025459c4e8683910a1fd82c05868cddf2d2a96a'}}, 'combined_core_bytes': 11773383, 'combined_core_decimal_mb': 11.773383, 'combined_core_mib': 11.227972984313965, 'required_metadata_bytes': 659, 'complete_runtime_bytes': 11774042, 'size_target_bytes': 6500000, 'size_pass': False, 'nncf_fake_quantize_ops': 67, 'constant_bytes_by_precision': {"<Type: 'int64_t'>": 400, "<Type: 'float32'>": 183848, "<Type: 'int8_t'>": 11119984, "<Type: 'int32_t'>": 44}, 'export_api': 'Ultralytics8.4.24 FP32 OpenVINO conversion; NNCF quantize_with_accuracy_control; absolute max_drop0.0079;targetCPU;MIXED;exactly300 training samples', 'detection_head_policy': 'Unmodified upstream ignored Add/Sub/Mul/Div detection-head patterns and Sigmoid; MIXED preset', 'onnx_fp16_policy': 'CPU FP32 ONNX export, onnxconverter-common FP16 conversion with FP32 IO; CPU EP may promote unsupported kernels', 'versions': {'ultralytics': '8.4.24', 'torch': '2.10.0', 'onnx': '1.23.2', 'onnxruntime': '1.24.4', 'openvino': '2026.4.1', 'nncf': '3.4.0', 'numpy': '2.4.6', 'mlflow': '2.22.2'}, 'selected_ptq': 'accuracy_aware'}, 'runtime_precision_counts': {'f32': 160, 'i32': 94, 'u8': 98, 'i8': 64}, 'openvino_version': '2026.4.1-22982-e213a147257-releases/2026/4', 'settings': {'performance_hint': 'LATENCY', 'num_streams': 1, 'threads': 2}, 'compilation_seconds': 0.8122128999093547}`.
Hardware/software: `{'cpu': 'Intel(R) Core(TM) i5-7200U CPU @ 2.50GHz', 'physical_cores': 2, 'logical_cores': 4, 'ram_bytes': 17049018368, 'os': 'Windows-11-10.0.26200-SP0', 'python': '3.12.9 (tags/v3.12.9:fdb8142, Feb  4 2025, 15:27:58) [MSC v.1942 64 bit (AMD64)]', 'openvino': '2026.4.1-22982-e213a147257-releases/2026/4', 'opencv': '5.0.0', 'psutil': '7.2.2'}`. Requested monitored soak 3600.0s; actual 3600.061s. Warmup 60s runs in the same process before the primary monitored period. Capture wall 3660.061s; with shutdown 3663.156s. No pipeline restart on media looping. Tracemalloc begins before warmup; post-warmup analysis excludes warmup. Sampling interval 1s; full telemetry persisted rather than retained in an accumulating Python list.
CPU1 deployment targets previously failed. This task exercises its selected artifact without promoting it or overriding that acceptance. No retraining, quantization rerun, resolution change, GPU/NPU or fallback backend. Input static batch1 640x640, CPU LATENCY/one stream/two threads as validated by CPU1. A shared scheduler may select three frames; the static artifact runs each once in order, then real NMS rescales boxes to source coordinates before tracking/geofences. Pure model latency excludes preprocessing/NMS; separate timers record those and tracking/escalation routing. No dummy detector.
The host is shared, not exclusively isolated. Tracemalloc adds measured instrumentation overhead. One-hour claims apply only to this workstation and configuration. Temperature is unavailable unless the host exposes a supported CPU sensor; frequency on Windows can be nominal and cannot independently establish thermal throttling.

## Feeds and throughput

Three nominal 30 FPS feeds sampled 1-in-4 cap operational FPS at 22.5; these native-rate feeds cap it at 19.7305. Neither cap reaches 45. The sampler remains enabled.
Operational integrated FPS **2.455**; separately measured ready-tensor engine capacity **5.405878126335157 FPS**. The 45 FPS operational gate is **FAIL**. Engine capacity also fails 45 FPS. Capacity never substitutes for camera throughput. Frame completion timestamps during the 3600-second period define throughput; stop drain is excluded. All raw sampler skips and true selected-frame overruns remain separately counted. Actual RTSP test NOT RUN.
| Camera | Source | Source FPS | Soak eval FPS | Captured total | Evaluated total | Skips | True overruns | Rewinds |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| camera_01: Fabric Weaving Feed | data/test_factory_clip.mp4 | 25.000 | 0.818 | 91502 | 3013 | 68626 | 19863 | 6 |
| camera_02: Chemical Storage Bay | Confidence_Calibration/benchmark/media/chemical_hazard_01_hazmat_training.webm | 29.946 | 0.818 | 109604 | 3011 | 82203 | 24390 | 55 |
| camera_03: Loading Bay | Confidence_Calibration/benchmark/media/no_helmet_01_workers_roof.webm | 23.976 | 0.818 | 87753 | 3012 | 65814 | 18927 | 146 |

Source roles use public documentary/hazmat-exercise/rooftop-worker simulations. These are not installed weaving/chemical/loading-bay CCTV; original media provenance remains in CPU2/CME-OPT3 reports. Source hashes and native dimensions are in JSON. RTP network losses are not observable through OpenCV.

## Latency, CPU and memory

Pure OpenVINO latency milliseconds: `{'mean_ms': 392.376654791266, 'p50_ms': 300.2246, 'p95_ms': 844.4891, 'p99_ms': 1183.9616, 'min_ms': 164.4812, 'max_ms': 4034.1063}`. Separate preprocessing, NMS, tracking/escalation routing and capture-to-completion: `{'preprocess_ms': {'mean': 8.0249305690689, 'p50': 7.312, 'p95': 13.3537, 'p99': 22.662, 'min': 4.4183, 'max': 121.923}, 'nms_ms': {'mean': 2.1581036316325375, 'p50': 1.4206, 'p95': 5.5231, 'p99': 9.7494, 'min': 0.7524, 'max': 325.6606}, 'routing_ms': {'mean': 3.8408998190246195, 'p50': 2.97220004722476, 'p95': 10.987799963913858, 'p99': 18.985599977895617, 'min': 0.1311999512836337, 'max': 122.5753000471741}, 'end_to_end_ms': {'mean': 1727.0252150714732, 'p50': 1621.6047999914736, 'p95': 2628.3915999811143, 'p99': 3578.324000001885, 'min': 949.7937000123784, 'max': 11087.926899897866}}`. All measured calls, not the last bounded diagnostic cache, determine percentiles. Stop drain is excluded.
CPU: `{'process_mean_pct': 46.694608256107834, 'process_p95_pct': 58.5, 'process_peak_pct': 81.425, 'system_mean_pct': 87.56969952260602, 'system_peak_pct': 100.0, 'process_normalized': {'mean': 46.694608256107834, 'p50': 47.275, 'p95': 58.5, 'p99': 61.525, 'min': 5.05, 'max': 81.425}, 'process_raw': {'mean': 186.77843302443134, 'p50': 189.1, 'p95': 234.0, 'p99': 246.1, 'min': 20.2, 'max': 325.7}, 'system': {'mean': 87.56969952260602, 'p50': 88.2, 'p95': 100.0, 'p99': 100.0, 'min': 61.5, 'max': 100.0}, 'normalization': 'Process CPU divided by four logical CPUs; machine normalized 0-100%, raw percent also retained'}`. Raw process CPU can exceed 100%; machine normalized process CPU divides by four logical cores. Both percent series remain available.
Memory: `{'rss_start_mb': 556.01953125, 'rss_mean_mb': 557.4147744225639, 'rss_peak_mb': 584.56640625, 'rss_end_mb': 484.55859375, 'rss_slope_mb_per_hour': -8.500439841970135, 'tracemalloc_start_mb': 149.84399700164795, 'tracemalloc_peak_mb': 170.74703121185303, 'tracemalloc_end_mb': 151.63624668121338, 'leak_detected': False, 'analysis': {'process_rss_mb': {'leak_detected': False, 'evidence_sufficient': True, 'slope_mb_per_hour': -8.500439841970135, 'final_twenty_minute_slope_mb_per_hour': -186.6098193520659, 'early_window_mean_mb': 554.9041622899159, 'final_window_mean_mb': 541.8729087752525, 'window_growth_mb': -13.031253514663376, 'material_growth_threshold_mb': 27.745208114495796, 'slope_threshold_mb_per_hour': 11.09808324579832, 'reason': 'No sustained material upward trend supported by all indicators; bounded cache/history fill is allowed'}, 'tracemalloc_current_mb': {'leak_detected': False, 'evidence_sufficient': True, 'slope_mb_per_hour': 2.0007871447969934, 'final_twenty_minute_slope_mb_per_hour': -2.7188639395936827, 'early_window_mean_mb': 149.70904844268028, 'final_window_mean_mb': 151.05740051397973, 'window_growth_mb': 1.3483520712994448, 'material_growth_threshold_mb': 7.485452422134014, 'slope_threshold_mb_per_hour': 2.994180968853606, 'reason': 'No sustained material upward trend supported by all indicators; bounded cache/history fill is allowed'}}, 'system_ram': {'mean': 71.46503791069924, 'p50': 71.2, 'p95': 73.0, 'p99': 73.2, 'min': 69.6, 'max': 74.0}, 'conclusion': 'No evidence of sustained memory growth/leak during the 60-minute run.'}`. Units MiB (2^20 bytes). RSS covers native memory that Python tracing may miss. Python allocation peak and end are independently captured; slight allocator/cache fluctuation alone does not imply a leak.
Memory heuristic: after warmup, require a materially positive whole-run slope, first-to-final stable-window increase, AND a materially positive final-20-minute slope before flagging sustained growth. RSS minimum material growth is 10 MiB and Python minimum 1 MiB; relative growth threshold is 5% of early-window memory and slope threshold at least 2%/hour. These thresholds were defined before measurement. Fixed history/cache filling that plateaus is distinguished from continuing growth. Top ten positive allocation deltas are saved at 15/30/45/60 minutes. This is evidence for a finite one-hour run, not proof that every possible workload is leak-free.
Memory conclusion: **No evidence of sustained memory growth/leak during the 60-minute run.**.


| Memory metric (MiB) | Start | Mean | Peak | End | Slope MiB/hour |
|---|---:|---:|---:|---:|---:|
| Process RSS | 556.020 | 557.415 | 584.566 | 484.559 | -8.500 |
| Python traced | 149.844 | 150.649 | 170.747 | 151.636 | 2.001 |

## Thermal and reliability

Thermal/frequency report: `{'temperature_available': False, 'frequency_available': True, 'temperature': None, 'frequency': {'mean': 2511.0, 'p50': 2511.0, 'p95': 2511.0, 'p99': 2511.0, 'min': 2511.0, 'max': 2511.0}, 'mean_temp_c': None, 'peak_temp_c': None, 'mean_freq_mhz': 2511.0, 'min_freq_mhz': 2511.0, 'throttling_detected': None, 'throttling_evidence': 'Unable to determine due to unavailable telemetry: no exposed CPU thermal-limit or OS throttling counter. Frequency variation alone is not evidence of thermal throttling.', 'frequency_source': 'psutil.cpu_freq; on Windows reported frequency may be nominal and is not a per-core real-time thermal counter'}`. Missing metrics are null/blank, never fabricated zeros. Frequency change alone is not labeled throttling.
Health: `{'crashes': 0, 'reconnects': 0, 'read_failures': 0, 'buffer_overruns': 63180, 'capture_threads_stable': True, 'native_thread_growth_suspected': False, 'native_thread_trend': {'leak_detected': False, 'evidence_sufficient': True, 'slope_mb_per_hour': 0.07619768559758493, 'final_twenty_minute_slope_mb_per_hour': 0.0, 'early_window_mean_mb': 34.87563025210084, 'final_window_mean_mb': 35.0, 'window_growth_mb': 0.12436974789915922, 'material_growth_threshold_mb': 2, 'slope_threshold_mb_per_hour': 2, 'reason': 'No sustained material upward trend supported by all indicators; bounded cache/history fill is allowed'}, 'native_threads_min': 34.0, 'native_threads_max': 37.0, 'ring_capacity_bounded': True, 'clean_shutdown': True}`. Thread counts `{'before': 15, 'before_shutdown': 35, 'after_shutdown': 10}`; active capture workers after stop `[]`. Event histories/resolved records are bounded to 1024 in this harness and archived to the existing JSONL event store; active safety incidents are never evicted. CPU2 rings remain 15 slots, timing diagnostic histories remain 4096 entries, and per-frame timing records are streamed to disk. Alert storage: `{'retention_limit': 1024, 'retained_events': 0, 'archived_events': 0, 'log_bytes': 0}`.
Failures: `[]`. All three streams loop independently; loop sessions reset tracking/escalation according to CPU2 behavior without restarting the process, clock or telemetry.

## Six 10-minute windows

| Window | FPS | Mean inference ms | P95 ms | System CPU % | RSS MiB | Python MiB | Temp C | MHz |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0-10 min | 2.596 | 371.159 | 776.227 | 87.295 | 554.908 | 149.708 | NA | 2511.000 |
| 10-20 min | 2.535 | 379.710 | 733.014 | 87.107 | 557.270 | 150.048 | NA | 2511.000 |
| 20-30 min | 2.544 | 379.124 | 819.131 | 86.406 | 560.420 | 150.646 | NA | 2511.000 |
| 30-40 min | 2.423 | 396.865 | 867.353 | 87.506 | 563.363 | 150.744 | NA | 2511.000 |
| 40-50 min | 2.064 | 467.465 | 1116.007 | 90.435 | 566.696 | 151.693 | NA | 2511.000 |
| 50-60 min | 2.565 | 375.113 | 824.206 | 86.679 | 541.873 | 151.057 | NA | 2511.000 |

Early/final window comparison: `{'fps_change_pct': -1.212068278816747, 'latency_change_pct': 1.0655372454928314, 'rss_change_pct': -2.3489849133939034}`. Workload, source clips, runtime settings and sampling remain unchanged. Performance variation is retained and not used to invent a thermal diagnosis.

## Definition of Done

| Check | Result |
|---|---|
| Required Git branch used | PASS |
| OpenVINO INT8 engine verified | PASS |
| 3 concurrent simulated feeds active | PASS |
| ESE-CPU2 async ingestion reused | PASS |
| 60-minute / 3600-second continuous run completed | PASS |
| No unrecoverable crashes | PASS |
| Process RSS monitored | PASS |
| tracemalloc monitored | PASS |
| No evidence of sustained RSS growth | PASS |
| No evidence of sustained Python allocation growth | PASS |
| Thread/worker count stable | PASS |
| Ring buffers stable | PASS |
| CPU utilization recorded | PASS |
| CPU frequency recorded | PASS |
| CPU temperature recorded | UNAVAILABLE |
| Thermal throttling analyzed | UNAVAILABLE |
| Operational aggregate FPS documented | PASS |
| Inference-capacity FPS documented where required | PASS |
| >=45 FPS task target | FAIL |
| Latency mean/P95/P99 documented | PASS |
| cpu_soak_report.json generated | PASS |
| CPU/RAM telemetry graphs generated | PASS |
| Final soak report generated | PASS |
| CME-3 tracking updated | PASS |
| ESE-CPU3 OVERALL | FAIL |

## Artifacts and offline delivery

JSON `SED_3_Stress_Testing/reports/cpu_soak_report.json`, telemetry `SED_3_Stress_Testing/reports/cpu_soak_timeseries.csv`, inference timing `SED_3_Stress_Testing/reports/cpu_soak_inference.csv`, frame timing `SED_3_Stress_Testing/reports/cpu_soak_frames.csv`. CPU, memory, FPS and frequency graphs use only measured samples. Tests and CME-3 run metadata are attached during finalization after the real full-duration evidence exists.
Required feature branch `feature/atlantis-cpu-soak-test` is based on completed local CPU2. Exactly two task commits are saved after actual 60-minute evidence; user reports organization access revoked, so no push/PR now. Later sync: `git push -u origin feature/atlantis-cpu-soak-test`. Verified Git bundle, artifact/media archive and local tracking archive remain ignored under `ESE_CPU3_Soak_Test/backups/`.

[CPU graph](cpu_soak_cpu.png), [memory graph](cpu_soak_memory.png), [throughput graph](cpu_soak_fps.png), [frequency graph](cpu_soak_thermal.png).

References: [OpenVINO CPU properties](https://docs.openvino.ai/nightly/openvino-workflow/running-inference/inference-devices-and-modes/cpu-device.html), [tracemalloc limits and snapshots](https://docs.python.org/3/library/tracemalloc.html), [psutil frequency and sensors](https://psutil.readthedocs.io/stable/index.html).

CME-3 local MLflow run `fe9542a0ce14495d9ec4ffeab152dedd`, source commit `137bb0b32840631c70f6c7be61d4d54f99a09d2e`.

Related tests: `{"sed1": {"file": "ESE_CPU3_Soak_Test/reports/updated_sed1_tests_terminal.txt", "tests": 28, "passed": 28}, "sed2": {"file": "ESE_CPU3_Soak_Test/reports/existing_sed2_tests_terminal.txt", "tests": 35, "passed": 35}, "sed3": {"file": "ESE_CPU3_Soak_Test/reports/combined_sed3_tests_terminal.txt", "tests": 23, "passed": 23}}`; all 86 passed.

## Files and source identity

Source changes relative to CPU2: ["M\t.gitignore", "A\tESE_CPU3_Soak_Test/README.md", "A\tESE_CPU3_Soak_Test/__init__.py", "A\tESE_CPU3_Soak_Test/analysis.py", "A\tESE_CPU3_Soak_Test/capacity.py", "A\tESE_CPU3_Soak_Test/delivery_check.py", "A\tESE_CPU3_Soak_Test/engine.py", "A\tESE_CPU3_Soak_Test/finalize.py", "A\tESE_CPU3_Soak_Test/offline_backup.py", "A\tESE_CPU3_Soak_Test/report.py", "A\tESE_CPU3_Soak_Test/requirements.txt", "A\tESE_CPU3_Soak_Test/soak.py", "A\tESE_CPU3_Soak_Test/sync_when_access_returns.ps1", "M\tExperiment_Tracking/scripts/validate_registry.py", "M\tREADME.md", "M\tSED_1_Multi_Camera/scripts/models.py", "M\tSED_1_Multi_Camera/scripts/stream_manager.py", "M\tSED_2_Alert_Escalation/scripts/event_store.py", "M\tSED_2_Alert_Escalation/scripts/factory.py", "M\tSED_2_Alert_Escalation/scripts/mock_iot_relay.py", "M\tSED_3_Stress_Testing/README.md", "M\tSED_3_Stress_Testing/scripts/resource_monitor.py", "A\tSED_3_Stress_Testing/scripts/soak_test.py", "A\tSED_3_Stress_Testing/tests/test_cpu_soak.py"]

Additional evidence files: ["ESE_CPU3_Soak_Test/reports/capacity_terminal.txt", "ESE_CPU3_Soak_Test/reports/combined_sed3_tests_terminal.txt", "ESE_CPU3_Soak_Test/reports/compile_validation_terminal.txt", "ESE_CPU3_Soak_Test/reports/delivery_validation.json", "ESE_CPU3_Soak_Test/reports/existing_sed2_tests_terminal.txt", "ESE_CPU3_Soak_Test/reports/inference_capacity.json", "ESE_CPU3_Soak_Test/reports/inference_capacity_samples.csv", "ESE_CPU3_Soak_Test/reports/registry_validation_terminal.txt", "ESE_CPU3_Soak_Test/reports/smoke_terminal.txt", "ESE_CPU3_Soak_Test/reports/soak_terminal.txt", "ESE_CPU3_Soak_Test/reports/updated_sed1_tests_terminal.txt", "SED_3_Stress_Testing/reports/ESE_CPU3_Soak_Test_Report.md", "SED_3_Stress_Testing/reports/cpu_soak_allocation_deltas.json", "SED_3_Stress_Testing/reports/cpu_soak_cpu.png", "SED_3_Stress_Testing/reports/cpu_soak_fps.png", "SED_3_Stress_Testing/reports/cpu_soak_frames.csv", "SED_3_Stress_Testing/reports/cpu_soak_inference.csv", "SED_3_Stress_Testing/reports/cpu_soak_memory.png", "SED_3_Stress_Testing/reports/cpu_soak_report.json", "SED_3_Stress_Testing/reports/cpu_soak_smoke_allocation_deltas.json", "SED_3_Stress_Testing/reports/cpu_soak_smoke_cpu.png", "SED_3_Stress_Testing/reports/cpu_soak_smoke_fps.png", "SED_3_Stress_Testing/reports/cpu_soak_smoke_frames.csv", "SED_3_Stress_Testing/reports/cpu_soak_smoke_inference.csv", "SED_3_Stress_Testing/reports/cpu_soak_smoke_memory.png", "SED_3_Stress_Testing/reports/cpu_soak_smoke_report.json", "SED_3_Stress_Testing/reports/cpu_soak_smoke_report.md", "SED_3_Stress_Testing/reports/cpu_soak_smoke_thermal.png", "SED_3_Stress_Testing/reports/cpu_soak_smoke_timeseries.csv", "SED_3_Stress_Testing/reports/cpu_soak_thermal.png", "SED_3_Stress_Testing/reports/cpu_soak_timeseries.csv"]

Removed files: none. The measured harness is preserved in source commit 137bb0b32840631c70f6c7be61d4d54f99a09d2e. The evidence commit adds relative camera-config path normalization and its regression test; the required command uses the same absolute default config and unchanged runtime settings.
