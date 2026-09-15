# ESE-CPU2 Benchmark Report

**Overall: FAIL.** Evidence generated 2026-10-08T16:08:07.269192+00:00. No earlier completion or original deadline compliance is claimed.

## Architecture and method

RTSP/HTTP/USB/file → independent capture worker → fixed 15-slot raw ring → phase-zero 1-in-4 sampler → fair shared inference → calibrated CME-OPT3 ByteTRACK → unchanged 15 evaluated-observation confirmation → SED-2. Skipped raw frames cause no detector/tracker updates. The existing SED-1 manager is refactored; this folder contains validation/delivery tools, not a second production pipeline.
The sampler records the modulo decision during raw ring write and the scheduler consumes the oldest still-retained selected slot. Every successfully decoded raw frame enters the ring. No inference/tracking executes under its lock. Each slot retains its selection/consumption state: replacing an unread selected slot is a true overrun; replacement of a skipped slot is normal reuse. The three independent rings cannot exceed 15 raw references each. Per-camera sequence starts at zero and never rewinds on file loop/reconnect. Session changes reset tracker/escalation state; the raw sampling phase continues.
Original implementation: elapsed-time sampling at the existing config default 5 FPS, two-slot latest queues, loss on oldest-frame replacement. The same three native-FPS paced inputs, source model, image size, micro-batch, CPU thread configuration, thresholds, tracking and escalation are used for the 180-second baseline and optimized phases. New sampling intentionally replaces the old 5 FPS target; baseline is not inflated to an invented 30 FPS inference target.
Original baseline source SHA256 `f28148525c69e8baae45ec57574fbabe01676dea7c8b68b8f29ced730b6d8c01`, Git `f239c770dfdaea862b4e108f3dacd3abc8c72484`. Baseline ran before any SED-1 edits. Optimized source commit `068bf411281c40582011a9ea884c566adbe18360`; source SHA256 `cf9cdb1523b68db0350cff144d14194cdd7aeafd7927391abe7dd8d989bf8b97`. Three-frame warmup precedes measurement. Capture windows: baseline 180.015s, optimized 180.015s. Total optimized with shutdown drain 186.867s. All selected frames remaining at stop are drained and accounted for.
CPU: existing SED-3 ResourceMonitor at one-second intervals, priming/shutdown excluded. Process percent is divided by four logical CPUs to use a machine-normalized 0–100 scale; system CPU includes all workstation activity. Both are disclosed and must be below 40 for the CPU check. Effective Ultralytics CPU thread count is three; OpenCV internal threads one. Original baseline metadata requested two threads before warmup but Ultralytics select_device resets them to NUM_THREADS=3; its corrected field and original requested value remain disclosed. Benchmark now records torch.get_num_threads. No affinity, artificial inference sleep, lower image size or replacement backend is used.
Environment: `{'platform': 'Windows-11-10.0.26200-SP0', 'cpu': 'Intel64 Family 6 Model 142 Stepping 9, GenuineIntel', 'logical_cpus': 4, 'physical_cpus': 2, 'ram_bytes': 17049018368, 'torch': '2.10.0+cpu', 'ultralytics': '8.4.24', 'opencv': '5.0.0', 'precision': 'PyTorch FP32', 'model': 'Backend/best.pt', 'model_sha256': 'c4aba081f6357e23a7370a5f7cf98eff2c6faa0c4c20a2d4dcb8bcabdd490061', 'imgsz': 640, 'torch_threads': 3, 'cv_threads': 1, 'micro_batch': True}`. CPU1 optimized exports remain local, unpromoted: source PyTorch FP32 is the actual production default. No retraining or checkpoint change. Capture frames remain at native resolution; detector uses its existing 640-pixel letterbox/NMS preprocessing. Source-file decode is wall-paced to simulate live arrivals, independent of inference.

## Three feeds and sampling

Source protocol: **local video simulation**. Actual RTSP protocol test: **NOT RUN** (no endpoints). Network RTP packet loss: **not directly observable through OpenCV**. No fabricated network-loss zero is claimed. Camera names identify intended deployment roles, not actual chemical-storage/loading-bay scene verification. Chemical source is a public hazmat exercise and loading source is rooftop workers; weaving uses the existing historical factory documentary. Public-video provenance is in `Confidence_Calibration/benchmark/source_manifest.csv` and `CME_OPT3_ByteTrack/reports/CME_OPT3_Benchmark_Report.md`. Source hashes, dimensions and durations are recorded in the metrics JSON.
| Camera / deployment role | Actual local source | Native FPS | Captured | Selected | Evaluated total | Intentional skips | Sustained eval FPS |
|---|---|---:|---:|---:|---:|---:|---:|
| camera_01: Fabric Weaving Feed | data/test_factory_clip.mp4 | 25.000 | 4501 | 1126 | 103 | 3375 | 0.544 |
| camera_02: Chemical Storage Bay | Confidence_Calibration/benchmark/media/chemical_hazard_01_hazmat_training.webm | 29.946 | 5390 | 1348 | 102 | 4042 | 0.539 |
| camera_03: Loading Bay | Confidence_Calibration/benchmark/media/no_helmet_01_workers_roof.webm | 23.976 | 4315 | 1079 | 102 | 3236 | 0.539 |

Raw sampler skips are exactly phase-zero selection: `74.989%`. Actual compute-frame reduction = 1 − evaluated/captured = **97.839%**. Values above 75% here include genuine lost selected work; they are **not** extra successful optimization. Evaluated total includes drain for conservation; sustained FPS uses evaluations completed within the capture window, with per-camera drain counts in CSV. Baseline evaluated FPS was measured as total evaluated divided by capture time and includes drain; use it as approximate throughput, not a pure sustained-window observation.

## Ring, latency and reliability

| Camera | Capacity | Mean occupancy/write | Max | Circular reuses | Normal reuses | True overruns | Read failures | Reconnects | Worker crashes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| camera_01 | 15 | 14.942 | 15 | 4387 | 3364 | 1023 | 0 | 0 | 0 |
| camera_02 | 15 | 14.953 | 15 | 5277 | 4031 | 1246 | 0 | 0 | 0 |
| camera_03 | 15 | 14.942 | 15 | 4202 | 3225 | 977 | 0 | 0 | 0 |

Conservation: captured = intentional skips + selected; selected = evaluated + true overruns + inference/routing drops + pending selected. Every camera passes these equations and pending selected is zero after drain. Ring max/mean counters cover every write; bounded timing/depth histories retain their most recent 4096 entries. Frame-age summaries include stop drain and can exceed the running 15-frame horizon during that separately reported drain. CSV contains one-second occupancy observations. Capture timestamp and pre-ring-write timestamp live on FramePacket; scheduler timestamps selection and inference start. Full JSON reports capture→selection, selection→inference and capture→inference mean/max milliseconds.
Native network open/read deadlines are 2000ms via OpenCV FFmpeg parameters; failed network opens/reads use cancelable exponential retry from 0.25s to 4s. Backend limitations are explicit: USB reads do not have a portable OpenCV timeout. An uninterruptible driver makes stop raise and prevents an overlapping restart; no successful cleanup is claimed until threads actually join. Fake blocked/reconnect sources test isolation and cancellation. Local EOF loops increment session_generation without being counted as a decode failure. Exceptions are recorded without exposing private source URLs.

[Measured CPU and ring occupancy graph](cpu_and_buffer_timeseries.png)

## CPU comparison

Task-stated baseline **95% is reference only**. Measured data:
| Metric | Baseline | Optimized | Target | Result |
|---|---:|---:|---|---|
| Concurrent active feeds | 3 | 3 | 3 | PASS |
| System mean CPU % | 97.382 | 96.702 | <40 | FAIL |
| System peak CPU % | 100.000 | 100.000 | diagnostic | — |
| Normalized process mean CPU % | 73.109 | 74.687 | <40 | FAIL |
| Normalized process peak CPU % | 88.050 | 88.525 | diagnostic | — |
| Frames evaluated total | 301 | 307 | ~25% captured | FAIL |
| Compute frame reduction % | 97.881 | 97.839 | ~75 | FAIL |
| Unintentional captured-frame losses | 2128 | 3246 | 0 | FAIL |
| True overruns | 2128 | 3246 | 0 | FAIL |

Absolute and relative CPU reduction: `{'system_mean': {'absolute_pp': 0.6800129870130149, 'relative_pct': 0.6982922838842945}, 'normalized_process_mean': {'absolute_pp': -1.5779342532467666, 'relative_pct': -2.158343710475099}}`. Relative formula `(baseline mean − optimized mean)/baseline mean × 100`. Negative values mean increased CPU. The sampler is correct but the actual FP32 detector cannot sustain the selected demand on this two-core laptop. Buffers cap backlog and disclose the deficit instead of silently discarding it. Resolving the performance gates requires a separately validated faster detector runtime/hardware; slowing sources, selecting fewer than 1-in-4 or suppressing counters would invalidate this task.

## CME-OPT3 timing

The unit test verifies only evaluated observations advance real ByteTRACK and the unchanged 15-observation state machine. With raw 30 FPS, nominal 7.5 eval FPS gives a 15/FPS estimate of 2s (first-to-fifteenth observation span is 14/FPS). Each source here has its own native cadence, and actual inference capacity is lower:
| Camera | Native/4 target eval FPS | Actual sustained eval FPS | Expected 15-observation duration |
|---|---:|---:|---:|
| camera_01 | 6.250 | 0.544 | 27.553s |
| camera_02 | 7.487 | 0.539 | 27.837s |
| camera_03 | 5.994 | 0.539 | 27.837s |

This timing estimate is throughput-based, not a measured ground-truth violation alert delay. Camera roles are unannotated public simulations; previous missed-hazard findings remain. The 2s real-time timing target fails when actual cadence is this low; state-machine logic still passes and no threshold was lowered.

## Tests and acceptance

Required file: {'tests': 21, 'passed': 21, 'status': 'PASS'}. All SED-1 tests including required file: {'tests': 28, 'passed': 28, 'status': 'PASS'}. Tracker/SED-2 tests: {'tests': 35, 'passed': 35, 'status': 'PASS'}. SED-3 monitor tests: {'tests': 6, 'passed': 6, 'status': 'PASS'}. No live workers or scheduler remain after the official run. Required tests cover fixed capacity, 0/4 boundary, exact 25/75 accounting, ordering/conservation under threaded stress, separate buffers, three sources, slow/failed camera isolation, retry/backoff, session rewind, detector failure, stop/restart, overlap refusal and real ByteTRACK→15 observations→SED-2.

| Definition of Done | Verdict |
|---|---|
| Required branch used | PASS |
| stream_manager.py refactored | PASS |
| One independent capture thread per camera | PASS |
| 3 concurrent streams supported | PASS |
| 15-frame ring buffer per camera | PASS |
| Ring buffers thread-safe | PASS |
| 1-in-4 deterministic sampler implemented | PASS |
| ~75% inference-frame reduction verified | FAIL |
| Actual evaluated FPS documented | PASS |
| Capture decoupled from inference | PASS |
| Fabric weaving stream active | PASS |
| Chemical storage stream active | PASS |
| Loading bay stream active | PASS |
| 180-second integration benchmark completed | PASS |
| Unintentional application-level frame drops = 0 | FAIL |
| True buffer overruns = 0 | FAIL |
| Intentional sampler skips reported separately | PASS |
| Measured baseline CPU documented | PASS |
| Optimized mean CPU <40% | FAIL |
| CME-OPT3 15-frame timing compatibility verified | FAIL |
| test_stream_manager.py passing | PASS |
| No orphan capture threads | PASS |
| Stream failure isolation verified | PASS |
| CME-3 tracking updated | PASS |
| ESE-CPU2 OVERALL | FAIL |

## Tracking, files and offline handoff

CME-3 local MLflow run `36188fd4676b4f6abbc6d774539ffc76`, experiment type `async_video_ingestion`, config `ESECPU2-async-ring15-sample4-v1`. Trained detector and policy registry rows are unchanged; an ingestion experiment row is appended. Lineage: CME-OPT2 selected FP32 detector → CPU2 async ingestion → CME-OPT3 tracker → SED-2. CPU1 formats remain recorded as optional failed deployment candidates.
Created/modified source files in first commit: `['.gitignore', 'Backend/main.py', 'ESE_CPU2_Async_RTSP/README.md', 'ESE_CPU2_Async_RTSP/__init__.py', 'ESE_CPU2_Async_RTSP/benchmark.py', 'ESE_CPU2_Async_RTSP/finalize.py', 'ESE_CPU2_Async_RTSP/offline_backup.py', 'ESE_CPU2_Async_RTSP/plot.py', 'ESE_CPU2_Async_RTSP/requirements.txt', 'ESE_CPU2_Async_RTSP/run_logged.py', 'ESE_CPU2_Async_RTSP/sync_when_access_returns.ps1', 'Experiment_Tracking/scripts/validate_registry.py', 'README.md', 'SED_1_Multi_Camera/README.md', 'SED_1_Multi_Camera/configs/3_cameras.json', 'SED_1_Multi_Camera/scripts/camera_source.py', 'SED_1_Multi_Camera/scripts/config.py', 'SED_1_Multi_Camera/scripts/models.py', 'SED_1_Multi_Camera/scripts/ring_buffer.py', 'SED_1_Multi_Camera/scripts/stream_manager.py', 'SED_1_Multi_Camera/tests/test_frame_drop.py', 'SED_1_Multi_Camera/tests/test_stream_isolation.py', 'SED_1_Multi_Camera/tests/test_stream_manager.py', 'SED_2_Alert_Escalation/tests/test_tracker.py']`. Additional second-commit files: this report, measured JSON/CSV, CPU graph, terminal outputs, acceptance summary and updated Experiment_Tracking/experiments.csv. Removed files: none.
Exactly two task commits are saved locally. The branch was newly created from completed local CPU1 HEAD; prior branches/history remain preserved. This is the task-specified feature branch, so reviewable changes stay grouped on it. No push/PR was attempted while organization access is revoked. Source commit is shown above; both final commit IDs are recorded in ignored `ESE_CPU2_Async_RTSP/backups/delivery_manifest.json` after commit two. Later sync: `git push -u origin feature/atlantis-async-rtsp`. A verified complete Git bundle is actually cloned to confirm recovery; runtime ZIP restores the ignored source model/media and local MLflow store.

References: [OpenCV timeout property support](https://docs.opencv.org/4.13.0/d4/d15/group__videoio__flags__base.html), [Python Event and thread joining](https://docs.python.org/3/library/threading.html). Native backend timeouts are configured at open; joined thread state is checked explicitly.

Final delivery audit: delivery_validation.json verifies identical input/model/runtime settings, actual 180-second windows, counter conservation, unchanged trained-model/policy history and the CME-3 run. The baseline SHA identifies the actual Windows working file; the saved Git-blob SHA is separately recorded because Git normalizes working-file line endings.

Selected arrival demand: 19.730505994005995 frames/s across three feeds; measured sustained evaluated throughput: 1.62208516593867 frames/s. Zero-loss processing cannot be claimed at that deficit.
