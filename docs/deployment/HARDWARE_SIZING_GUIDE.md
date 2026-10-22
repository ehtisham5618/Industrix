# IndustriX Hardware Sizing Guide

| | |
|---|---|
| Document version | 1.0.0 (FDD-2, Sprint 4) |
| Applies to | detector `cme-opt2-focal-cosine-12class-v1` (`Backend/best.pt`, SHA256 `c4aba081…0061`) and its exports |
| Status | Draft for production review: **no profile is production-approved until validated on the target hardware** |
| Evidence | `reports/fdd2/hardware_probe_*.json`, ESE-CPU1/ESE-CPU3, EAP-3/EAP-4/EAP-5, FDD-1 reports |

Every number below is labelled **Measured** (with its source and conditions), **Estimate** (with
its derivation) or **Not yet benchmarked**. Measured values come from one machine; they are
evidence for that machine, not guarantees for others.

## 1. What actually runs (verified in code)
| Component | Fact | Source |
|---|---|---|
| Detector | Ultralytics YOLOv8s, 12 classes, input 640×640, batch 1 | `Hazard_Expansion/configs/12class_data.yaml`, `Backend/main.py` |
| Artifacts | PyTorch FP32 `best.pt` 22,498,282 B · ONNX FP16 22,409,010 B · OpenVINO INT8 11,773,383 B (XML+BIN) | measured file sizes |
| Inference paths | `/predict`: PyTorch on CPU (or CUDA if the host has it). Streams: `INFERENCE_ENGINE=pytorch` (default) or `openvino` (INT8, CPU only, 640 only) | `Backend/main.py` `/streams/start` |
| ONNX FP16 | benchmark artifact only; **not used by any serving path** | ESE-CPU1, EAP-3 `.dockerignore` |
| Concurrency | `/predict` is an `async` endpoint running blocking inference: requests are serialised on the event loop (EAP-4 finding) | `Backend/main.py` |
| Streams | up to 4 cameras; per-camera 15-slot ring buffers; 1-in-4 frame sampling; one shared detector, frames evaluated sequentially | SED-1 / ESE-CPU2 |
| Other processes | Streamlit dashboard (separate process); EAP-5 watchdog (~40 MB RSS) | EAP-5 soak |
| Second model | QCI-2 ResNet18 surface classifier: separate, optional, not loaded by the detector API | QCI-2 |
| Storage written at runtime | incident SQLite + snapshots (`/data` in the container), SED-2 alert JSONL, rotated logs | EAP-3, EAP-5 |
| Offline | `YOLO_OFFLINE`/`YOLO_AUTOINSTALL=false`, loopback health checks, no cloud inference client | FDD-1 offline tests |

Not supported / not implemented: multi-GPU, TensorRT, NPU, ONNX Runtime serving, model batching
across requests, horizontal scaling. GPU inference exists only implicitly through PyTorch and is
**not tested** in this project.

## 2. Measured evidence (single host)
Host for all measurements: Intel Core i5-7200U (2 cores / 4 threads, AVX2, no AVX-512), 15.9 GB
RAM, Windows 11, no GPU, **shared developer laptop** (browser/IDE running).

| Measurement | Result | Conditions | Source |
|---|---|---|---|
| PyTorch FP32 full predict | p50 388 ms, p95 778 ms, p99 1,287 ms, 2.25 img/s; model load +131 MB RSS; peak 457 MB | 100 iterations, warm, 2 fixtures, 2.2 cores used | `reports/fdd2/hardware_probe_pytorch_fp32.json` (FDD-2) |
| OpenVINO INT8 full predict (letterbox+infer+NMS) | p50 291 ms, p95 510 ms, p99 771 ms, 2.95 img/s; load +71 MB; peak 336 MB | same | `reports/fdd2/hardware_probe_openvino_int8.json` |
| Pure engine latency, 200 iterations | FP32 p50 350 ms · ONNX FP16 p50 262 ms · INT8 p50 132 ms | ready tensor, ESE-CPU1 settings | `SED_3_Stress_Testing/reports/quant_report.json` |
| INT8 engine capacity | 5.41 fps (LATENCY hint, 2 threads, 1 stream) | ready tensors, no camera I/O | `ESE_CPU3_Soak_Test/reports/inference_capacity.json` |
| 3 camera streams, INT8, 60 min | **2.455 fps aggregate**; RSS mean 557 MiB, peak 585 MiB; process CPU 47% of machine; system CPU 88%; 63,180 sampler skips | 3 local video feeds, ByteTRACK + SED-2 | `SED_3_Stress_Testing/reports/ESE_CPU3_Soak_Test_Report.md` |
| `/predict` load, 4 h, 2 clients | 2.20 req/s; p50 795 ms, p95 1,790 ms; service RSS 360–495 MB; private bytes ~594→600 MB (growth flagged) | PyTorch, HTTP | `reports/eap4/` |
| Container image | 1,542,234,302 B unpacked (bundled, CPU torch + OpenVINO) | EAP-3 | `reports/eap3/` |
| Watchdog | ~40 MB RSS, flat over 60 min | EAP-5 soak | `reports/eap5/soak/` |
| Dashboard | Streamlit process; RSS **not yet benchmarked** separately | — | — |

Observations from the evidence:
- Accuracy cost of INT8: mAP50 −1.03 pp versus FP32 (fails the ESE-CPU1 < 1 pp gate; baseline failure).
- Memory does not scale linearly with streams: one detector is shared; streams add ring buffers,
  decode and tracker state (3 streams ≈ 557 MiB versus 336–457 MB for single-image inference).
- On this CPU the integrated 3-stream pipeline reached **2.455 fps total**, far below a 45 fps
  target (ESE-CPU3 gate FAIL). Throughput, not RAM, is the binding constraint on 2-core CPUs.

## 3. Sizing methodology
**RAM** (avoid double counting: a measured peak RSS already includes model and working memory):

`RAM_required = OS_baseline + Σ peak_RSS(service processes) + headroom`

where `peak_RSS(detector API)` is measured under the target workload (it already contains the
model, per-inference working memory, decode buffers and stream rings), plus the dashboard and
watchdog RSS, and headroom covers temporary allocations and growth. Only when a measured peak is
unavailable, use the component form
`OS_baseline + model_load_delta + peak_working_memory + per_stream_buffers × streams + app_overhead + headroom`
and label the result an estimate.

**CPU/throughput:** required evaluated frames/s = Σ over cameras (camera FPS × sampling ratio).
The implementation samples 1 frame in 4 per camera and evaluates frames sequentially on one
detector, so the needed capacity is roughly `streams × camera_fps / 4`. Compare it with the
**measured integrated** fps on the candidate hardware, not the pure-engine capacity. Do not assume
linear scaling with cores or streams.

**Storage:** OS + runtime (container image 1.54 GB unpacked, or a Python environment of similar
size) + model artifacts (22.5 MB PyTorch; +11.8 MB INT8) + incident DB and snapshots + logs
(EAP-5: 5 MB × 4 watchdog logs, 20 MB × 2 per service output log) + free-space headroom. Incident
growth per day is **not yet benchmarked**: measure DB and snapshot growth under the target alert
rate.

## 4. Deployment profiles
| | Development / validation | Small edge (image / 1 stream) | Multi-stream edge gateway (2–4 streams) | Accelerated (GPU) |
|---|---|---|---|---|
| Operating mode | native or container, PyTorch FP32 | container `bundled`, PyTorch `/predict` or OpenVINO stream engine | OpenVINO INT8 stream engine (`INFERENCE_ENGINE=openvino`), container | PyTorch on CUDA |
| CPU | x86-64 with AVX2; 2C/4T works (**tested**) | x86-64 AVX2, ≥ 4 physical cores recommended (**estimate**: 2C/4T saturated at 2.2 req/s) | x86-64 AVX2, ≥ 8 cores recommended (**estimate**; 2C/4T measured 2.455 fps for 3 streams) | any supported by the GPU host |
| RAM | 16 GB tested (≥ 8 GB estimate) | Estimate ≥ 4 GB: API peak 0.46–0.5 GB measured + dashboard (not benchmarked) + watchdog 0.04 GB + OS + ≥ 50% headroom | Estimate ≥ 8 GB: 3-stream peak 0.59 GB measured + dashboard + OS + headroom | Not yet benchmarked |
| GPU | not required | not required | not required (INT8 is CPU-only) | **untested**: CUDA build of PyTorch required; image ships CPU wheels only |
| Storage | ≥ 10 GB free (estimate) | ≥ 5 GB + incident growth (estimate) | ≥ 10 GB + incident/snapshot growth (estimate) | Not yet benchmarked |
| Camera workload | images or local files | 1 stream (assumption) | 2–4 streams; ≤ 4 is the code limit (fact); FPS/resolution are assumptions to measure | not benchmarked |
| Expected performance | measured on i5-7200U (see §2) | **Not yet benchmarked** on target | **Not yet benchmarked** on target; 2-core reference 2.455 fps aggregate | **Not yet benchmarked** |
| Status | tested on one host | expected to work, not validated | expected to work, throughput not validated | unsupported / unknown |
| Limitations | shared laptop numbers | serialised `/predict`; no SLA | sampler skips frames under load (63,180 in 60 min); 45 fps gate failed | no CUDA image; GPU path never exercised |

## 5. Compatibility and prerequisites
| Item | Tested | Expected to work, not tested | Unsupported / unknown |
|---|---|---|---|
| OS | Windows 11 (native); Linux in Docker (Debian bookworm image, EAP-3; watchdog tests EAP-5) | other x86-64 Linux distributions | macOS, ARM (aarch64, Jetson), 32-bit |
| Python | 3.12.9 (full stack), 3.14.3 (backend + dashboard) | 3.11 (watchdog minimum) | < 3.11 |
| CPU features | AVX2 (i5-7200U) | AVX-512/VNNI CPUs (may speed up INT8) | CPUs without AVX2: not tested |
| Runtimes | torch 2.10.0+cpu, ultralytics 8.4.24, OpenVINO 2026.4.1 | — | ONNX Runtime serving, TensorRT |
| GPU/CUDA | none | CUDA PyTorch on NVIDIA GPU | AMD/Intel GPU, NPU |
| Container | Docker Desktop 29.7.2 (WSL2 engine), image < 1.8 GB | other Docker engines | Kubernetes manifests (none exist) |
| Models | local files only; SHA256 verified at startup in the container | — | runtime download: disabled |

## 6. Benchmark procedure (before approving a target device)
1. Identify the host: `python -m FDD_2_Hardware_Taxonomy.hardware_probe` (records CPU, cores, RAM, OS,
   runtime versions, artifact sizes and SHA256; measures PyTorch FP32 and OpenVINO INT8 with warm-up,
   p50/p95/p99 and peak RSS). Run on an otherwise idle machine and keep the JSON.
2. API load: `python -m EAP_4_Load_Test.run_load_test --profile short-soak --target-url http://127.0.0.1:8000`
   (then `six-hour --confirm-long-run` for acceptance): throughput, latency percentiles, RSS and
   private-bytes drift (< 5% gate) and trend.
3. Streams: ESE-CPU3 soak (`SED_3_Stress_Testing/scripts/soak_test.py --duration 3600 --engine openvino --streams N`)
   with the real cameras: integrated fps, sampler skips, CPU, RSS.
4. Full system: `python -m FDD_1_Release_Regression.run_release_gate` on the target.
5. Record GPU memory if a GPU path is approved (not implemented in the probe today).

## 7. Decision process
Answer before choosing hardware: cameras and their resolution/FPS · acceptable end-to-end latency ·
CPU-only mandatory? · GPU available and supported? · RAM/storage available · must run fully offline
(supported) · required uptime and recovery (EAP-5 watchdog restarts within its budget). Then size
with §3, pick a §4 profile, and run §6 on the actual device. **Approve only after the measured
results meet agreed acceptance criteria.**

## 8. Open acceptance criteria (not defined in the repository)
- Target end-to-end latency (p95) for `/predict` and for stream alerts.
- Required camera count, resolution and evaluated FPS per site (the only prior target, 45 fps
  operational, failed on the reference laptop).
- Absolute memory ceiling per process/container and storage retention period.
- Approved hardware SKU(s) for the edge gateway.
- Resolution of the EAP-4 private-bytes growth finding before long unattended operation.

## Glossary
RSS: resident memory of a process · private bytes: committed memory (Windows `vms`) · p50/p95/p99:
latency percentiles · INT8/FP16/FP32: numeric precision of model weights · integrated fps: frames
actually evaluated by the full camera pipeline per second · engine capacity: model-only throughput
on ready tensors · sampler skip: a camera frame not evaluated because the ring/sampler moved on.

## Change history
| Version | Date | Change |
|---|---|---|
| 1.0.0 | 2026-10-22 | First evidence-based guide (FDD-2) |
