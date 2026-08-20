# Textile Defect Detection and Industrial Hazard Expansion

ESE-CPU3: [one-hour OpenVINO CPU soak tools and offline sync](ESE_CPU3_Soak_Test/README.md),
[actual continuous-run report](SED_3_Stress_Testing/reports/ESE_CPU3_Soak_Test_Report.md).

ESE-CPU2 async capture task: [implementation and offline sync](ESE_CPU2_Async_RTSP/README.md),
[measured three-stream acceptance report](SED_1_Multi_Camera/reports/ESE_CPU2/ESE_CPU2_Benchmark_Report.md).

Computer vision proof of concept for textile defect detection and industrial
safety monitoring, developed for Devlogix Technology.

The project started as a 7-class textile defect detector and was expanded into a
12-class model by adding five industrial hazard classes.

## Classes

Textile defect classes:

- `baekra`
- `color issues`
- `contamination`
- `cut`
- `gray stitch`
- `selvet`
- `stain`

Industrial hazard classes:

- `chemical hazard`
- `fire`
- `no helmet`
- `smoke`
- `water leak`

## Repository Structure

```text
Textile-Defect-Detection/
|-- Backend/
|   |-- fastapi_endpoint.ipynb
|   `-- main.py
|-- Frontend/
|   |-- app.py
|   |-- README.md
|   `-- requirements.txt
|-- Confidence_Calibration/
|   |-- configs/
|   |-- scripts/
|   |-- benchmark/
|   |-- reports/
|   `-- tests/
|-- Experiment_Tracking/
|   |-- configs/
|   |-- reports/
|   |-- scripts/
|   |-- experiments.csv
|   |-- model_registry.csv
|   `-- alert_policy_registry.csv
|-- SED_1_Multi_Camera/
|   |-- configs/
|   |-- reports/
|   |-- scripts/
|   `-- tests/
|-- SED_2_Alert_Escalation/
|   |-- configs/
|   |-- reports/
|   |-- scripts/
|   `-- tests/
|-- SED_3_Stress_Testing/
|   |-- configs/
|   |-- reports/
|   |-- scripts/
|   `-- tests/
|-- Hazard_Expansion/
|   |-- 01_prepare_combined_dataset.ipynb
|   |-- 02_improve_existing_model.ipynb
|   |-- 03_train_expanded_model.ipynb
|   |-- 04_evaluate_and_compare.ipynb
|   `-- content_runtime/              # ignored local/Colab runtime artifacts
|-- Preprocessing/
|   |-- notebooks/
|   |-- reports/
|   `-- scripts/
|-- Training/
|   `-- Textile_Defect_Detection_Training.ipynb
|-- requirements.txt
|-- .gitignore
`-- LICENSE.txt
```

Large datasets, model checkpoints, runtime outputs, images, and training result
artifacts are not stored in GitHub. They are kept in Google Drive.

## Google Drive Artifacts

Main Drive folder:

https://drive.google.com/drive/u/0/folders/1f9qfY8KkIFtAXe1REnx_I-fhNaUEdgkU

Drive contents:

```text
Drive root folder/
|-- textile_defect_yolov8_final.zip       # local folder name: final_dataset
|-- combined_dataset.zip                  # 12-class combined dataset
`-- Training_Results/
    |-- yolov8s_textile_initial/          # baseline 7-class training outputs
    |-- yolov8s_improved_7class/          # improved 7-class checkpoint/results
    |-- Expanded_12-class_model/          # expanded 12-class checkpoint/results
    `-- hazard_reports/                   # final report, matrices, examples
```

Important local runtime folders used during development:

- `final_dataset/`: extracted 7-class textile dataset, ignored by Git.
- `Hazard_Expansion/content_runtime/combined_dataset/`: extracted 12-class
  combined dataset, ignored by Git.
- `Hazard_Expansion/content_runtime/improved_model_results/`: local copy of the
  improved 7-class `best.pt` and `results.json`, ignored by Git.
- `Hazard_Expansion/content_runtime/expanded_model_results/`: local copy of the
  expanded 12-class results, ignored by Git.
- `Backend/best.pt`: deployed expanded 12-class checkpoint, ignored by Git.

## Main Workflows

### 1. Preprocessing

The original textile preprocessing workflow lives in:

```text
Preprocessing/notebooks/dataset_preprocessing.ipynb
```

Standalone helpers:

```powershell
python Preprocessing/scripts/validate_yolo_dataset.py --dataset final_dataset/
python Preprocessing/scripts/dataset_statistics.py --dataset final_dataset/ --output Preprocessing/reports/
```

### 2. Baseline Training

The original YOLOv8s 7-class baseline training workflow lives in:

```text
Training/Textile_Defect_Detection_Training.ipynb
```

Baseline metrics:

| Metric | Value |
|---|---:|
| Precision | 76.97% |
| Recall | 74.76% |
| mAP@50 | 78.82% |
| mAP@50-95 | 47.12% |

### 3. Hazard Expansion

The hazard expansion workflow is directly under `Hazard_Expansion/`:

```text
01_prepare_combined_dataset.ipynb
02_improve_existing_model.ipynb
03_train_expanded_model.ipynb
04_evaluate_and_compare.ipynb
```

Notebook 4 performs the final comparison across:

- Experiment A: historical 7-class baseline
- Experiment B: improved 7-class model
- Experiment C: expanded 12-class model

The final Definition of Done rule is:

- at least `2/5` hazard classes must reach `>= 70%` mAP@50
- at least `1/3` of the remaining hazard classes must reach `>= 60%` mAP@50

Current expanded-model DoD result: `PASS`.

Passing classes:

- `no helmet`: 89.4% AP@50
- `water leak`: 70.5% AP@50
- `fire`: 62.1% AP@50 support pass

Primary weak classes:

- `chemical hazard`: 49.1% AP@50
- `smoke`: 57.3% AP@50

### 4. Confidence Calibration and False-Positive Reduction

CME-2 lives in:

```text
Confidence_Calibration/
```

It adds an alert-policy layer around the expanded 12-class model without
retraining. The baseline config represents the existing behavior: a single YOLO
detection is enough to alert. The calibrated config adds per-class thresholds
and temporal confirmation for the hazard classes.

Benchmark status: measured. The frame-replay temporal benchmark passes the
CME-2 DoD with `75%` false-alert reduction and `0` missed true violations.
Public Wikimedia clips were also audited and documented separately; they expose
base-model domain shift rather than alert-policy failure.

The benchmark media folder is ignored by Git:

```text
Confidence_Calibration/benchmark/media/
```

The detailed benchmark report is in:

```text
Confidence_Calibration/reports/benchmark_report.md
```

### 5. Model Versioning and Experiment Tracking

CME-3 lives in:

```text
Experiment_Tracking/
```

Sprint 4 tracking uses lightweight persistent registries in Git, with large
weights and datasets kept in Google Drive. MLflow is optional for local UI
inspection; the committed CSV/YAML files are the source of truth.

Tracked registries:

- `Experiment_Tracking/experiments.csv`
- `Experiment_Tracking/model_registry.csv`
- `Experiment_Tracking/alert_policy_registry.csv`

Current pitch candidate:

- Detector: `cme1-expanded-12class-v1`
- Weights: `Backend/best.pt` locally and Drive
  `Training_Results/Expanded_12-class_model/best.pt`
- Alert policy: `cme2-alert-calibrated-v1`
- Config: `Confidence_Calibration/configs/calibrated_thresholds.yaml`

Open optional MLflow UI after installing the focused tracking dependency:

```powershell
python -m pip install -r Experiment_Tracking/requirements-mlflow.txt
python Experiment_Tracking/scripts/backfill_existing_runs.py
mlflow ui --backend-store-uri Experiment_Tracking/mlruns
```

Validate the registry:

```powershell
python Experiment_Tracking/scripts/validate_registry.py
```

Sprint 4 summary:

```text
Experiment_Tracking/reports/Sprint_4_Experiment_Summary.md
```

## Backend

The backend is a FastAPI app in `Backend/main.py`. It loads `Backend/best.pt`,
which should be the expanded 12-class checkpoint.

Run locally:

```powershell
python -m uvicorn Backend.main:api_app --host 127.0.0.1 --port 8000
```

Prediction endpoint:

```text
POST /predict
```

The endpoint accepts an uploaded image and returns detected class names,
confidence scores, and pixel bounding boxes.

Optional CME-2 alert policy:

```text
POST /predict?apply_alert_policy=true&frame_index=0&timestamp_sec=0.0
```

This preserves raw detections and adds an `alert_policy` object with calibrated
detections and confirmed temporal alerts.

## Frontend

The frontend is a Streamlit dashboard in `Frontend/app.py`.

Run locally after starting the backend:

```powershell
streamlit run Frontend/app.py
```

The dashboard uploads images to the FastAPI backend and displays detections on
the image. It does not run YOLO inference locally.

## 6. Multi-Camera Stream Architecture

SED-1 lives in:

```text
SED_1_Multi_Camera/
```

It refactors inference into a reusable multi-camera pipeline:

```text
Capture workers -> bounded latest-frame queues -> fair scheduler
-> shared YOLO detector -> per-camera geofence filter
-> per-camera CME-2 AlertPolicy -> camera-specific alerts/results
```

Key properties:

- supports 1-4 simulated camera feeds from video files
- uses one shared `cme1-expanded-12class-v1` detector by default
- preserves independent CME-2 temporal state per camera
- supports normalized polygon geofences per camera
- tracks captured, eligible, submitted, processed, configured skipped, overload
  dropped, and failed frames separately
- exposes optional FastAPI demo endpoints for camera status/results/alerts
- adds a Streamlit multi-camera status tab without replacing image inference

Configuration:

```text
SED_1_Multi_Camera/configs/cameras.yaml
SED_1_Multi_Camera/configs/benchmark.yaml
```

Benchmark:

```powershell
python SED_1_Multi_Camera/scripts/benchmark_multistream.py --streams 3 --duration-seconds 60 --warmup-seconds 5 --device 0
```

Local CPU benchmark evidence is stored in:

```text
SED_1_Multi_Camera/reports/
```

The local CPU-only environment (`torch 2.10.0+cpu`, CUDA unavailable) validates
that the architecture runs but does **not** satisfy the SED-1 performance DoD.
The measured 3-stream CPU run processed `10/104` eligible frames with `90.385%`
unexpected drops. Run the same benchmark on the target CUDA/T4 environment
before marking the `<5%` frame-drop performance requirement as passed.

## 7. Real-Time Alert Escalation

SED-2 lives in:

```text
SED_2_Alert_Escalation/
```

It adds a severity-tiered response layer after CME-2 confirmation and SED-1
multi-camera routing:

```text
Confirmed violation -> SeverityEngine -> EscalationManager -> ActionDispatcher
```

Severity tiers:

- `INFO`: structured log only
- `WARNING`: structured log plus dashboard warning/flash state
- `CRITICAL`: structured log, critical dashboard state, and safe mock IoT
  shutdown simulation

Configuration:

```text
SED_2_Alert_Escalation/configs/severity_rules.yaml
SED_2_Alert_Escalation/configs/action_mapping.yaml
```

Policy version:

```text
SED2-alert-escalation-v1
```

The default safety rules cover:

- `fire`
- `smoke`
- `water leak`
- `chemical hazard`
- `no helmet`

The state machine is monotonic during one active event (`INFO -> WARNING ->
CRITICAL`) and resolves only after the configured clear period. Geofence
overrides are supported, and multi-camera events remain isolated by camera,
hazard, and geofence. The mock IoT relay is software-only and never controls
physical hardware.

Validate SED-2:

```powershell
python -m unittest discover -s SED_2_Alert_Escalation\tests
```

Current deterministic validation result: `15` tests passed. The detailed report
is in:

```text
SED_2_Alert_Escalation/reports/SED_2_Validation_Report.md
```

## 8. Stress Testing & Latency Benchmarking

SED-3 lives in:

```text
SED_3_Stress_Testing/
```

It benchmarks the current integrated pipeline:

```text
SED-1 streams -> CME-1 detector -> CME-2 confirmation
-> SED-1 geofences -> SED-2 escalation
```

The committed local run is a real 3-stream, 30-minute CPU stress test:

| Metric | Result |
| --- | ---: |
| Duration | 1804.22 s |
| Streams | 3 |
| Device | CPU |
| Frames processed | 635 |
| Aggregate FPS | 0.352 |
| P95 inference latency | 4151.81 ms |
| P95 end-to-end latency | 13683.47 ms |
| Unexpected frame drop | 96.607% |
| RAM peak | 1057.74 MB |
| Crashes | 0 |
| RAM leak evidence | none detected |

This CPU-only run validates sustained stability and clean shutdown, but it does
not support a literal zero-latency claim or a low-latency 3-stream performance
claim on this hardware. GPU/T4 validation should be run separately with:

```powershell
python SED_3_Stress_Testing/scripts/run_stress_test.py --streams 3 --duration-seconds 1800 --warmup-seconds 60 --sample-interval 5 --device 0 --output-dir SED_3_Stress_Testing/reports
```

Report:

```text
SED_3_Stress_Testing/reports/SED_3_Benchmark_Report.md
```

## CME-OPT1 - Targeted Hazard Dataset Augmentation

Chemical hazard (ID 7) and smoke (ID 10) now have a reproducible training-only
mining and augmentation workflow in
[`CME_OPT1_Hard_Negative_Augmentation/`](CME_OPT1_Hard_Negative_Augmentation/README.md).
It supports color jitter, HSV, lighting/sheen, Mosaic and smoke overlays, with
review manifests, class-balance figures, QC evidence and CME-3 dataset tracking.

The validated v3 output adds **505 training images**: 205 independent real
references and 300 derivatives; train 4,974 -> 5,479, with validation 777 and test
334 unchanged. Chemical annotations grow 340 -> 494; smoke 901 -> 1,014.

**Technical acceptance PASS:** 238 unique verified negative-source examples
(142 chemical, 96 smoke), including 28 observed errors and 210 verified visual
confusers under the task's "causes or could cause" definition. Positives and
derivatives do not inflate this count. Review was performed by Codex with source
metadata; human peer approval remains separate. All 12 classes are represented;
unequal counts and inherited source-family overlap are disclosed.
[Results](CME_OPT1_Hard_Negative_Augmentation/reports/RESULTS.md) include the complete
12-class before/after table; the
[class-balance graph](CME_OPT1_Hard_Negative_Augmentation/reports/class_balance_before_after.png)
and terminal evidence are under the task's `reports/` folder.

## CME-OPT3 — ByteTRACK temporal filtering

The [task folder](CME_OPT3_ByteTrack/README.md) documents camera/class-specific
ByteTRACK integration, strict 15-frame confirmation, stream lifecycle cleanup,
and the existing SED-2 escalation path. Run video inference with:

```powershell
python Backend/main.py --source data/test_factory_clip.mp4 --tracker bytetrack.yaml --persist-frames 15
```

The [measured factory benchmark](CME_OPT3_ByteTrack/reports/CME_OPT3_Benchmark_Report.md)
records **overall FAIL**: false alerts fell from 9 to 0, but all 17 annotated
no-helmet events were missed. The 49 regression tests pass; numerical acceptance
is separate. No detector retraining or confidence-policy relaxation was performed.

## ESE-CPU1 — CPU quantization and offline delivery

The [separate task folder](ESE_CPU1_Quantization/README.md) contains the
training-only 300-image calibration pipeline, validated ONNX FP16/OpenVINO INT8
exports, CPU accuracy/latency benchmark, tests and offline recovery instructions.
The [measured report](SED_3_Stress_Testing/reports/ESE_CPU1_Quantization_Report.md)
records each acceptance gate independently. Source detector and production
Backend defaults remain intact. Generated deployment binaries stay outside Git.

The task is saved as exactly two local commits on
`feature/atlantis-openvino-quant`. When organization access returns, sync with
`git push -u origin feature/atlantis-openvino-quant`. A verified Git bundle and
separate deployment archive are kept in `ESE_CPU1_Quantization/backups/`.

## IFE-UI1 — multi-stream operator console

The existing [Streamlit app](Frontend/app.py) now renders three independently
updating feeds, real detector/tracker overlays and backend CPU/RSS/operational
FPS telemetry. Start the backend separately, then run
`streamlit run Frontend/app.py --server.port 8501` and press **Start three feeds**.
See the [task instructions](IFE_UI1_Streamlit_Console/README.md) for runtime,
real-browser validation and offline recovery. Measured UI evidence is in
`Frontend/reports/`. Work is saved as two local commits on
`feature/atlantis-streamlit-ui`; use the task's sync script after organization
access returns. No push or PR is attempted while access is revoked.

## IFE-UI2 - local incident auditing and PDF export

The [incident-audit task](IFE_UI2_Incident_Audit/README.md) extends confirmed
ByteTRACK/SED-2 events with local SQLite storage, native cropped evidence and
one ReportLab generator used by CLI and Streamlit. Incident History includes
**Export Incident PDF** and local download. Runtime data stays outside Git;
`reports/sample_incident.pdf` is explicitly marked SAMPLE / DEMONSTRATION.
The measured report and offline recovery instructions are in the task docs.
Two local commits on `feature/atlantis-incident-pdf` can be synced after access
returns using `git push -u origin feature/atlantis-incident-pdf`.

## Sprint 4 CPU-Ready Demo

The [IFE-UI3 package](IFE_UI3_Demo_Packaging/README.md) validates the integrated
12-class YOLOv8s detector, OpenVINO INT8 CPU engine, three local async feeds,
ByteTRACK with 15 evaluated observations, SED-2, Streamlit, SQLite evidence and
offline ReportLab PDF download. It includes deterministic demo footage, the
required root E2E test and an actual HD browser recording. See the
[integration report](reports/IFE_UI3_End_to_End_Demo_Report.md) for actual
performance, offline guard scope and acceptance status. The original numerical
CPU targets remain unmet on this workstation. Video upload is pending manual
action; repository access is revoked, so the PR/merge and
`v0.4.0-sprint4-cpu-ready` release tag are pending. Exactly two local task commits
and verified recovery archives preserve the work for ordinary later sync.

## QCI-1 - Surface Defect Dataset Ingestion & Segmentation Setup

The [QCI-1 package](QCI_1_Surface_Defect_Segmentation/README.md) adds typed local
image/annotation validation, bounded preprocessing, split/leakage checks and
manifests to the existing preprocessing workflow. Run
`python Preprocessing/scripts/prepare_surface_segmentation.py --config QCI_1_Surface_Defect_Segmentation/configs/qci1_segmentation.yaml`
using the backend environment; reports are written under `reports/qci1/`.
QCI tests are the four root `tests/test_qci1_*.py` modules.
The actual seven-class textile corpus contains boxes, so segmentation readiness
is explicitly BLOCKED. Genuine publisher KolektorSDD fine masks were acquired
separately:366 verified pairs,33 original quarantines, binary classes kept separate.
Run with `configs/kolektor_segmentation.yaml` for real-mask preparation. Data are
CC BY-NC-SA4.0 for noncommercial research/review; commercial use needs permission.
No masks or segmentation model are invented. Two local commits and recovery archives preserve
the work for sync after organization access returns.

## QCI-2 ? Defect Classifier & Anomaly Heatmap

The [QCI-2 package](QCI_2_Defect_Classifier/README.md) consumes the successful
QCI-1 curated dataset, preserving302/48/16 splits. It fine-tunes a verified
local ResNet18 checkpoint for mask-derived normal/defect classification and
provides typed predictions with genuine Grad-CAM model attribution.
Use the existing backend interpreter:

```powershell
python Training/train_qci2_classifier.py --config QCI_2_Defect_Classifier/configs/qci2_classifier.yaml
python -m QCI_2_Defect_Classifier.infer --image QCI_1_Surface_Defect_Segmentation/runtime/segmentation_dataset/images/test/kos18/Part0.jpg
python -m QCI_2_Defect_Classifier.run_checks
```

Weights stay local at `QCI_2_Defect_Classifier/runtime/run_v1/best.pt`.
See [actual model/heatmap review](reports/qci2/QCI_2_Production_Review.md) and
[all-test sanity grid](reports/qci2/classifier_heatmap_sanity_grid.png).
Data/model use is noncommercial research/review; commercial permission and
GitHub PR are pending. Two local commits and verified backups support later sync.

## QCI-3 local severity alarms

QCI-3 consumes the real QCI-2 normal/defect contract, adds monotonic INFO/WARNING/
CRITICAL activation states and durable, acknowledged local siren webhooks.
Default research rules keep the webhook disabled. See
[task documentation](QCI_3_Severity_IoT/README.md),
[dataset attribution and confirmed noncommercial scope](QCI_3_Severity_IoT/LICENSE_DATA.md),
and [measured review evidence](reports/qci3/QCI_3_Production_Review.md).
The dataset permission gate is resolved for the user's noncommercial research
and evaluation. Prior CPU size, accuracy and throughput gates retain their
original thresholds and are reported honestly in the follow-up evidence.
Two local task commits and verified recovery archives support later sync:

```powershell
./QCI_3_Severity_IoT/sync_when_access_returns.ps1
```

## QCI-4 edge telemetry and optional cloud failover

The local QCI pipeline now has typed health at `/edge/status`, a bounded telemetry
history, and an optional durable metadata spool with acknowledged ordered replay.
Cloud is disabled by default; local inference/alarms continue during service
outages. No images or heatmaps are uploaded. See
[QCI-4 documentation](QCI_4_Edge_Telemetry/README.md) and
[measured evidence](reports/qci4/QCI_4_Production_Review.md).
Run `./QCI_4_Edge_Telemetry/sync_when_access_returns.ps1` after repository access
returns to push the two local task commits normally.

## Notes for GitHub

The following are intentionally ignored and should remain in Drive/local storage:

- datasets and dataset zips
- `content_runtime/`
- `hazard_reports/`
- images
- `*.pt` checkpoints
- generated JSON runtime outputs
- YOLO `runs/`
- `Experiment_Tracking/mlruns/`

## Contact

GitHub username: `ehtisham5618`

Email: `ehtisham.malik5618@gmail.com`

### QCI-5: Local Incident PDF Reports

The existing Incident History exports ReportLab PDFs for persisted hazard and QCI-3 quality events. Offline CLI: python Backend/scripts/export_incident_pdf.py --incident-id INC-2026-001. Runtime output: reports/incidents/; reviewed sample: reports/qci5/sample_incident_report.pdf. Tests: python -m pytest QCI_5_Incident_PDF/tests -q. See [QCI-5 documentation](docs/QCI_5_Incident_PDF_Report_Generator.md) for evidence, download, telemetry and recovery details.

### EAP-1: Low-Light & CCTV Robustness Fine-Tuning

Fine-tunes the production 12-class detector (`Backend/best.pt`, unchanged) with deterministic training-only low-light, uneven-illumination, CCTV-compression, motion-blur, colour-cast and synthetic IR-style degradations, then compares baseline and candidate per lighting domain on identical test sets. No genuine infrared data exists in the repository, so real-IR robustness is recorded as not verified. Code: `EAP_1_LowLight_IR_Robustness/`; tests: python -m pytest EAP_1_LowLight_IR_Robustness/tests -q. See [EAP-1 documentation](docs/EAP_1_Low_Light_IR_Robustness.md) and the [review report](reports/eap1/EAP_1_Low_Light_IR_Robustness_Report.md).

### EAP-2: Model Regression Suite

Offline regression gate for the production detector: artifact hash, class map, real /predict contract, golden fixtures, test-split metrics vs a versioned baseline, CPU latency/memory. Run: python -m EAP_2_CI_Model_Regression.runner. See [EAP-2 documentation](docs/EAP_2_CI_Model_Regression.md).

### EAP-3: Lightweight Docker Image

Multi-stage CPU image for the FastAPI inference service (non-root, offline, real inference). Build: docker build -t industrix:eap3 . ; run: docker run -p 127.0.0.1:8000:8000 -v industrix-data:/data industrix:eap3. Size gate: python EAP_3_Lightweight_Docker/check_image_size.py industrix:eap3. See [EAP-3 documentation](docs/EAP_3_Lightweight_Docker.md).

### EAP-4: Continuous Load Test & Memory Profile

Load-tests the real POST /predict and profiles the service process (RSS drift gate < 5%, trend-based leak analysis, bounded latency histogram). Run: python -m EAP_4_Load_Test.run_load_test --profile smoke --target-url http://127.0.0.1:8000 (six-hour profile needs --confirm-long-run). See [EAP-4 documentation](docs/EAP_4_Load_Test_Memory_Profile.md).

### EAP-5: Auto-Restart Watchdog

Local-first supervisor for the FastAPI backend and Streamlit dashboard: loopback health checks, verified restarts with threshold/cooldown/backoff/rolling budget, degraded state, owned-process-only shutdown. Setup: powershell -ExecutionPolicy Bypass -File EAP_5_Watchdog/scripts/setup_watchdog.ps1 -Action validate (Linux: sh EAP_5_Watchdog/scripts/setup_watchdog.sh validate). See [EAP-5 documentation](docs/EAP_5_Auto_Restart_Watchdog.md).

### FDD-1: Code Freeze & Release Regression

One-command release gate over the frozen Sprint 3 code: full test suite vs baseline, real-model regression, live backend+dashboard under the watchdog, load/memory smoke, clean shutdown. Run: ESE_CPU1_Quantization/runtime/venv/Scripts/python.exe -m FDD_1_Release_Regression.run_release_gate. See [FDD-1 documentation](docs/FDD_1_Code_Freeze_Release_Regression.md).

### FDD-2: Hardware Sizing & Hazard Taxonomy

Evidence-based [hardware sizing guide](docs/deployment/HARDWARE_SIZING_GUIDE.md) and versioned [hazard taxonomy](docs/specifications/HAZARD_TAXONOMY.md) with a machine-readable manifest validated against the model configs (python -m FDD_2_Hardware_Taxonomy.taxonomy). Host benchmark: python -m FDD_2_Hardware_Taxonomy.hardware_probe.

### FDD-3: Production Runbook & Deployment Handoff

Operator package: [production runbook](docs/deployment/PRODUCTION_RUNBOOK.md), [deployment guide](docs/deployment/DEPLOYMENT_GUIDE.md), [troubleshooting](docs/deployment/TROUBLESHOOTING.md), [rollback and recovery](docs/deployment/ROLLBACK_AND_RECOVERY.md) and [handoff](docs/deployment/DEPLOYMENT_HANDOFF.md). Preflight: python -m FDD_3_Deployment_Handoff.validate_deployment; live check: python -m FDD_3_Deployment_Handoff.smoke_test.

### FDD-4: Product Demo Recording

Reproducible recording of the real dashboard and API: python -m FDD_4_Demo.record_demo (Playwright + Edge + ffmpeg, offline-guarded). Final take: reports/fdd4/demo/industrix_demo_20261022T175557Z.mp4 (132 s, 1080p). See the [storyboard](docs/demo/INDUSTRIX_DEMO_STORYBOARD.md) and [recording guide](docs/demo/RECORDING_GUIDE.md).

### FDD-5: Demo Day Dry Run

Repeatable rehearsal of the real product (readiness, watchdog startup, dashboard inference compared with /predict, failure recovery, crash auto-restart, clean restart): python -m FDD_5_Dry_Run.rehearse. Reports: reports/fdd5/rehearsal/. See the [dry-run guide](docs/demo/DEMO_DAY_DRY_RUN.md).
