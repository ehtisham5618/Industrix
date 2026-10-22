# IndustriX Troubleshooting

Version 1.0.0 (FDD-3). `$py` = the deployment interpreter. Run commands from the repository root.
First step for any problem: `& $py -m EAP_5_Watchdog status` and the tail of
`EAP_5_Watchdog/runtime/logs/backend.out.log`. **Back up `Backend/data/events.db` before any repair that touches data.**

| Symptom | Diagnose | Likely cause | Safe action | Verify | Escalate if |
|---|---|---|---|---|---|
| `ModuleNotFoundError` at start | `& $py -m FDD_3_Deployment_Handoff.validate_deployment` (`import:*` FAIL) | wrong interpreter or missing package | activate the right venv; `pip install -r requirements.txt -r Frontend/requirements.txt` | validator PASS | a pinned version conflicts |
| Validator `model_artifact` FAIL | message shows missing path or SHA mismatch | weights not provisioned / wrong file | copy the approved `best.pt`; never edit or "repair" weights | `model_artifact` PASS | no approved artifact available |
| Backend exits at startup: "No model checkpoint found" / "checksum mismatch" / "Failed to load model" | `logs/backend.out.log` | same as above (`INDUSTRIX_REQUIRE_MODEL=1`) | fix `INDUSTRIX_MODEL_PATH` / provision the artifact | `GET /health` 200 | persists with the approved file |
| `/health` 503 `model_unavailable` | `GET /health` | model optional and not loaded | provision model, restart | `model_loaded: true` | — |
| Port 8000/8501 in use; service `blocked` | `status` shows `blocked`; `Get-NetTCPConnection -LocalPort 8000 -State Listen` | another process (e.g. a manual uvicorn) owns the port | stop **that** process yourself after identifying it; the watchdog never kills it | `validate_deployment --expect-ports-free` PASS | the owner is unknown/critical |
| Service `degraded` (circuit open) | `status` (`restarts_window` = 5), `watchdog.jsonl` `circuit_open` | crash loop within the hour | read `logs/<service>.out.log` (+ `.1`), fix the cause, then `stop` and `start` | healthy, restarts stable | cause unclear after logs |
| Repeated `recovery_failed` | `watchdog.jsonl` | service restarts but never becomes healthy within 90–120 s (slow model load, broken config) | check logs; on slow hosts raise `recovery_timeout_seconds` in the watchdog config | recovered event | — |
| Dashboard "backend unavailable" | open the dashboard; `GET http://127.0.0.1:8000/health` | backend down or wrong `BACKEND_URL` | start backend / fix `BACKEND_URL` | dashboard loads predictions | — |
| `/predict` 400 "not a readable image" | response body | corrupt or non-image upload | send a valid JPG/PNG | 200 with detections | valid images rejected |
| `/predict` 422 | response body | missing multipart field `file` | send `file=@image` | 200 | — |
| Slow inference / high latency | `& $py -m FDD_2_Hardware_Taxonomy.hardware_probe` and EAP-4 smoke | CPU saturated, other apps, PyTorch engine | close other workloads; use `INFERENCE_ENGINE=openvino` for streams; see sizing guide | latency back to measured range | exceeds an agreed SLA (none defined yet) |
| Memory keeps growing | `status` + Task Manager / `GET /edge/status` | known slow private-bytes growth (EAP-4) | schedule a restart (`stop`/`start`) in a maintenance window | RSS back to baseline | growth faster than ~1.5 MB/h; report |
| Out of memory | `logs/backend.out.log`, system RAM | too many streams for the host | reduce streams; see sizing guide | stable | — |
| Camera stream errors | `GET /cameras/{camera_id}/status` | source path/RTSP unreachable | fix `CAMERA_CONFIG` sources | frames counting | — |
| Too many false alerts | `GET /alerts/active`, `/alerts` | low-light scenes, smoke/water-leak confusion (see taxonomy) | do not lower thresholds ad hoc; thresholds live in `Confidence_Calibration/configs/calibrated_thresholds.yaml` and need a re-calibration | — | always escalate threshold changes for review |
| Incident write errors (`INCIDENT_STORAGE_INIT_FAILED`, `status_write_failed`) | backend log / `watchdog.jsonl` | directory not writable, disk full, file locked | check permissions and disk (`validate_deployment`) | incidents listed at `/incidents` | DB corruption suspected: stop, back up, escalate |
| Disk space low | validator `disk_free` | logs/incidents/snapshots growth | archive (do not delete) old incident PDFs and snapshots after backup | ≥ 5 GB free | — |
| `docker build` fails | build output | missing `Backend/best.pt` in context, no network for base image | provision weights; build with network | image builds | — |
| Container exits immediately | `docker logs industrix` | model missing/mismatched (fail-fast) | mount/provision the approved model | `/health` 200 | — |
| Something tries to reach the internet | firewall logs | misconfiguration (e.g. QCI-4 cloud enabled) | keep `INDUSRIX_CLOUD_ENABLED=false`, `YOLO_OFFLINE=true` | — | any unexplained outbound traffic |
