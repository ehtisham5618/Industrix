# IndustriX Deployment Handoff

Version 1.0.0 (FDD-3) · prepared 2026-10-22

## A. Summary
IndustriX is a local, CPU-first industrial vision system: one YOLOv8s detector
(`cme-opt2-focal-cosine-12class-v1`, 7 textile-defect + 5 safety-hazard classes) served by a FastAPI
backend, a Streamlit operator dashboard, multi-camera stream processing with temporal confirmation and
SED-2 escalation, local incident logging and PDF reports, and the EAP-5 watchdog for automatic recovery.
- Repository: `https://github.com/devlogixtechnology/industrix`; work is stacked in PRs #1–#22 into
  `staging` (each depends on the previous one); deploy only a revision that passed the FDD-1 gate.
- Modes: native Windows (tested), Docker backend (tested in EAP-3), Linux native (watchdog only verified),
  GPU (unsupported). Details: [Deployment guide](DEPLOYMENT_GUIDE.md).
- Entry points: `uvicorn Backend.main:api_app` (8000), `streamlit run Frontend/app.py` (8501),
  `python -m EAP_5_Watchdog` (supervisor). Ownership boundary: the watchdog owns only processes it starts.

## B. Operational reference
| Need | Where |
|---|---|
| Install / configure / provision model | [Deployment guide](DEPLOYMENT_GUIDE.md) §3–6 |
| Start, stop, readiness, logs, monitoring | [Production runbook](PRODUCTION_RUNBOOK.md) |
| Problems | [Troubleshooting](TROUBLESHOOTING.md) |
| Failed change | [Rollback and recovery](ROLLBACK_AND_RECOVERY.md) |
| Hardware | [Hardware sizing guide](HARDWARE_SIZING_GUIDE.md) |
| Classes, thresholds, severities | [Hazard taxonomy](../specifications/HAZARD_TAXONOMY.md) |
| Tests | `python -m pytest -q` (full suite), `python -m FDD_1_Release_Regression.run_release_gate` (release gate) |

## C. Security and access
- Services bind to `127.0.0.1`. Exposing them on a LAN requires a reverse proxy with authentication:
  the API and dashboard have **no authentication** and the API allows any CORS origin.
- No secrets in Git. Values that may be sensitive (`QCI3_SIREN_URL`, `INDUSRIX_CLOUD_URL`, RTSP
  credentials inside `CAMERA_CONFIG`) belong in the service environment or a protected file.
- Incident DB, snapshots and PDFs contain operational images of people and equipment: restrict file
  access to operators and retain/delete according to site policy (no policy is defined in the repo).
- Model artifacts are read-only at runtime; verify their SHA256 on deployment.
- No formal security audit has been performed.

## D. Acceptance and known limitations
Verified on the reference host (2026-10-22): preflight 24/24, start, readiness in 23 s, smoke test 6/6
(real inference, invalid input 400, incidents, dashboard), graceful stop; FDD-1 gate with no new
regressions; EAP-5 watchdog recovery of a killed backend.
Not verified / open:
1. Possible slow memory growth in the backend (EAP-4: private bytes +1.5 MB/h; trend gate FAIL).
2. ESE-CPU1 INT8 gates fail (11.77 MB vs 6.5 MB; −1.03 pp mAP50).
3. No approved latency, error-rate, camera-count or memory SLAs.
4. Target edge hardware, GPU, Linux native services and physical offline operation untested.
5. Six-hour soak not completed (4 h run).
6. Taxonomy decisions pending: `chemical hazard` vs `water leak` annotation (C-1), textile definitions.
7. GitHub Actions has never run on the repository.
8. Rollback is manual; no artifact registry service or automated deploy pipeline.
Next steps: investigate memory growth; agree SLAs and the gateway SKU; run the target-device benchmark
(sizing guide §6); enable CI; resolve taxonomy C-1; automate rollback.

## E. Operator quick-start (validated 2026-10-22)
```powershell
$py = '<venv>\Scripts\python.exe'
& $py -m FDD_3_Deployment_Handoff.validate_deployment --expect-ports-free   # 1-2 prerequisites, config, model
& $py -m EAP_5_Watchdog start                                              # 3 start
& $py -m EAP_5_Watchdog status                                             # 4 ready: both 'healthy'
& $py -m FDD_3_Deployment_Handoff.smoke_test                               # 5 smoke test: SMOKE: PASS
Get-Content EAP_5_Watchdog/runtime/logs/backend.out.log -Tail 50          # 6 logs
& $py -m EAP_5_Watchdog stop                                               # 7 stop safely
```
