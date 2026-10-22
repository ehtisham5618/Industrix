# IndustriX Deployment Guide

Version 1.0.0 (FDD-3). Operations: [Production runbook](PRODUCTION_RUNBOOK.md). Hardware: [Hardware sizing guide](HARDWARE_SIZING_GUIDE.md).

## 1. Deployment modes
| Mode | Status | Notes |
|---|---|---|
| Native Python on Windows 11, CPU, watchdog-managed | **Tested** (FDD-3 quick-start, EAP-5) | reference host i5-7200U |
| Native Python on Linux, CPU | Documented, **not verified end-to-end** | watchdog + setup script verified in a Debian container (EAP-5); services not run on Linux |
| Docker image `industrix:eap3` (backend only), CPU | **Tested** in EAP-3 (16/16 container tests) | image deleted locally to save disk; rebuild with `docker build -t industrix:eap3 .` |
| OpenVINO INT8 stream engine (`INFERENCE_ENGINE=openvino`) | **Tested** for streams (ESE-CPU3) | CPU, 640 px only; INT8 fails the < 1 pp mAP gate (−1.03 pp) |
| GPU (CUDA) inference | **Unsupported / untested** | requirements and image use CPU wheels |
| Dashboard in Docker | **Not implemented** | run the dashboard natively |

## 2. Prerequisites
- Python 3.11+ (tested 3.12.9 full stack; 3.14.3 backend + dashboard). Windows 11 x86-64 or Linux x86-64; AVX2 CPU tested.
- Hardware: see the sizing guide (reference host: 2C/4T, 16 GB, ≥ 5 GB free disk as a planning estimate).
- Model artifacts (not in Git): `Backend/best.pt` (22,498,282 B, SHA256 `c4aba081f6357e23a7370a5f7cf98eff2c6faa0c4c20a2d4dcb8bcabdd490061`);
  optional `Backend/weights/openvino_int8/{model.xml,model.bin,metadata.yaml}` for the INT8 engine.
- Ports 8000 (backend) and 8501 (dashboard) free on 127.0.0.1.
- Write access to `Backend/data/` (or `INCIDENT_DATABASE`'s directory), `data/snapshots`, `EAP_5_Watchdog/runtime/`.
- Internet only during installation (pip, Docker base images). Runtime needs none.

## 3. Installation (native)
```powershell
git clone https://github.com/devlogixtechnology/industrix.git; cd industrix
git checkout <approved release revision>
python -m venv .venv; .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt -r Frontend/requirements.txt
# Optional INT8 engine: python -m pip install openvino==2026.4.1
# Provision Backend/best.pt (and the OpenVINO export) from the approved artifact store, then:
python -m FDD_3_Deployment_Handoff.validate_deployment --expect-ports-free
powershell -ExecutionPolicy Bypass -File EAP_5_Watchdog/scripts/setup_watchdog.ps1 -Action validate
```
Linux: `python3 -m venv .venv && . .venv/bin/activate`, same pip command, then
`sh EAP_5_Watchdog/scripts/setup_watchdog.sh validate`. The default `requirements.txt` resolves the
torch build pip selects for the platform; for a smaller CPU-only install use the pinned set in
`EAP_3_Lightweight_Docker/requirements-runtime.txt` (CPU wheels index).
The tested full-stack environment is `ESE_CPU1_Quantization/runtime/venv` (local, not in Git).

## 4. Installation (container, backend)
The image is defined by the repository `Dockerfile` (multi-stage: `builder` → `runtime` → `bundled`) and `.dockerignore`.
```powershell
docker build -t industrix:eap3 .                      # needs Backend/best.pt in the build context
docker run -d --name industrix -p 127.0.0.1:8000:8000 -v industrix-data:/data --read-only --tmpfs /tmp industrix:eap3
python -m FDD_3_Deployment_Handoff.smoke_test --no-dashboard
```
Weights-mounted variant: `docker build --target runtime -t industrix:eap3-runtime .` and
`-v <path>/best.pt:/models/best.pt:ro -e INDUSTRIX_MODEL_SHA256=c4aba081…0061`. See `docs/EAP_3_Lightweight_Docker.md`.

## 5. Configuration reference
All values are environment variables read by the code listed. None of the defaults is a secret.
| Name | Consumer | Default | Required | Format / meaning | Sensitive |
|---|---|---|---|---|---|
| `INDUSTRIX_MODEL_PATH` | `Backend/main.py` | `best.pt` or `Backend/best.pt` | no (yes in production) | path to the checkpoint; explicit path never falls back | no |
| `INDUSTRIX_REQUIRE_MODEL` | `Backend/main.py` | `0` (`1` in the container and watchdog config) | recommended `1` | `1` = refuse to start without a loadable model | no |
| `INDUSTRIX_MODEL_SHA256` | `Backend/main.py` | unset | recommended | 64-hex SHA256 the model must match | no |
| `INFERENCE_ENGINE` | `/streams/start` default | `pytorch` | no | `pytorch` or `openvino` | no |
| `CAMERA_CONFIG` | backend streams | `SED_1_Multi_Camera/configs/3_cameras.json` | for streams | JSON camera list (local files or RTSP) | may contain RTSP credentials: keep outside Git |
| `INCIDENT_DATABASE` | incidents, QCI-3, QCI-4 | `Backend/data/events.db` | no | SQLite path (container `/data/events.db`) | contains incident records |
| `INCIDENT_SNAPSHOTS` | incident snapshots | `data/snapshots` | no | directory | contains images |
| `INCIDENT_UI_TIMINGS_PATH` | incident UI timing log | unset | no | path | no |
| `QCI3_CONFIG` | QCI-3 alarms | built-in defaults | no | JSON config path (≤ 64 KiB) | no |
| `QCI3_SIREN_URL` | QCI-3 webhook | config value | no | siren webhook URL | **may be** (keep outside Git) |
| `QCI4_CONFIG` | QCI-4 telemetry | built-in defaults | no | JSON config path | no |
| `INDUSRIX_CLOUD_ENABLED` | QCI-4 sync (spelling as in code) | `false` | no | `true`/`false`; keep `false` for offline | no |
| `INDUSRIX_CLOUD_URL` | QCI-4 sync | unset | only if sync enabled | URL | **may be** |
| `QCI5_CONFIG` | QCI-5 PDF reports | built-in | no | JSON config path | no |
| `QCI5_DEMO_API_PORT` | QCI-5 demo server only | `8765` | no | port | no |
| `BACKEND_URL` | `Frontend/app.py` | `http://127.0.0.1:8000` | no | backend base URL | no |
| `DEPLOYMENT_MODE` | dashboard privacy indicator | `local` | no | label | no |
| `RUNTIME_EXTERNAL_SERVICES` | dashboard privacy indicator | empty | no | comma list of declared external services | no |
| `IFE_UI3_DEMO` | dashboard demo banner | unset | no | `true` enables demo text | no |
| `YOLO_OFFLINE`, `YOLO_AUTOINSTALL` | set by `Backend/offline_policy.py` | `true`, `false` | — | keep: prevents downloads/installs | no |
| `INDUSTRIX_WATCHDOG_CONFIG` | `EAP_5_Watchdog` | `EAP_5_Watchdog/configs/watchdog.json` | no | path to watchdog JSON | no |
Watchdog fields (ports, health URLs, thresholds, backoff) are documented in `docs/EAP_5_Auto_Restart_Watchdog.md`
and validated by `python -m EAP_5_Watchdog validate`. No `.env` file is used; set variables in the
service environment or the watchdog `env` block (values are never logged).

## 6. Model and data provisioning
- Provision `Backend/best.pt` from the approved store (not Git, not downloaded at runtime) and verify:
  `python -m FDD_3_Deployment_Handoff.validate_deployment` (`model_artifact` PASS) or
  `Get-FileHash Backend/best.pt -Algorithm SHA256`.
- Missing model: with `INDUSTRIX_REQUIRE_MODEL=1` startup fails with "No model checkpoint found";
  wrong file: "Model checksum mismatch"; without the flag `/predict` and `/health` return 503.
- Class map and taxonomy: `docs/specifications/hazard_taxonomy.v1.json`, checked by
  `python -m FDD_2_Hardware_Taxonomy.taxonomy` (must print CONSISTENT).
- Datasets are not needed at runtime (only for evaluation, e.g. the EAP-2 runner).

## 7. Offline operation
Verified logically, not by physical disconnection: model downloads disabled, health checks loopback-only,
socket-guard tests (EAP-2, EAP-5) show no outbound connections during inference, FDD-1 import checks find
no cloud inference clients, the container ran real inference with `--network none` (EAP-3). Keep QCI-4
cloud sync disabled. **Physical offline test: NOT VERIFIED.**

## 8. Deployment verification checklist
| # | Step | Command | Result on 2026-10-22 (reference host) |
|---|---|---|---|
| 1 | Imports, model, configs, ports, disk | `python -m FDD_3_Deployment_Handoff.validate_deployment --expect-ports-free` | PASS 24/24 (`reports/fdd3/quickstart_1_validate.txt`) |
| 2 | Start | `python -m EAP_5_Watchdog start` | started (`quickstart_2_start.txt`) |
| 3 | Readiness | `python -m EAP_5_Watchdog status` | both healthy after 23 s (`quickstart_3_ready_status.txt`) |
| 4 | Health, valid inference, invalid input, status, incidents, dashboard | `python -m FDD_3_Deployment_Handoff.smoke_test` | PASS 6/6 (`quickstart_4_smoke.txt`) |
| 5 | Graceful shutdown | `python -m EAP_5_Watchdog stop` | graceful, 2 s, ports freed (`quickstart_5_stop.txt`) |
| 6 | Regression | `python -m FDD_1_Release_Regression.run_release_gate` | FDD-1: no new failures (2 baseline CPU1 failures) |
