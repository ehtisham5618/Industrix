# IndustriX Demo Day — Official Dry Run (FDD-5)

One command rehearses the real product end to end: `FDD_5_Dry_Run/rehearse.py`. It reuses the FDD-3
deployment validator and smoke test, the EAP-5 watchdog and the FDD-4 browser automation; it does not add a
new engine, model or service. Storyboard for the presented demo: [INDUSTRIX_DEMO_STORYBOARD.md](INDUSTRIX_DEMO_STORYBOARD.md);
recorded backup video: [RECORDING_GUIDE.md](RECORDING_GUIDE.md).

Every check is `PASS`, `FAIL`, `BLOCKED` or `NOT VERIFIED`. The rehearsal is **READY** only when every
*required* check is `PASS`; a skipped required check is never counted as a pass.

## Commands (Windows 11, PowerShell, repository root)
```powershell
$py = 'ESE_CPU1_Quantization/runtime/venv/Scripts/python.exe'      # Python 3.12 with the full stack
& $py -m FDD_3_Deployment_Handoff.validate_deployment --expect-ports-free   # read-only readiness (FDD-3)
& $py -m FDD_5_Dry_Run.rehearse --preflight-only                   # stage A only; starts nothing
& $py -m FDD_5_Dry_Run.rehearse                                    # full dry run, about 4 minutes
& $py -m FDD_5_Dry_Run.rehearse --skip-ui --skip-restart           # quick API-only rehearsal (UI/restart NOT VERIFIED)
& $py -m pytest FDD_5_Dry_Run/tests -q                             # automated tests (no services needed)
```
Exit codes: 0 READY · 1 NOT READY · 2 stage A failed (nothing started) · 3 ports 8000/8501 already in use
(the rehearsal refuses to touch processes it did not start: run `python -m EAP_5_Watchdog stop` if they are
yours). Ctrl+C stops the rehearsal; the services it started are stopped in a `finally` block.

Live demo (presenter) start/stop, the same commands the rehearsal uses:
```powershell
& $py -m EAP_5_Watchdog start     # backend :8000 + dashboard :8501, supervised, auto-restart
& $py -m EAP_5_Watchdog status
& $py -m FDD_3_Deployment_Handoff.smoke_test    # 6 checks against the running services
& $py -m EAP_5_Watchdog stop --timeout 90
```
Dashboard: http://127.0.0.1:8501 · API health: http://127.0.0.1:8000/health

## Outputs
| Path | Content |
|---|---|
| `reports/fdd5/rehearsal/rehearsal_<UTC stamp>.json` | machine-readable report (Pydantic `RehearsalReport`): revision, environment, every check with status/detail/timing/evidence, resource samples, offline observations, readiness |
| `reports/fdd5/rehearsal/evidence_<stamp>/*.png` | dashboard screenshots taken during the run |
| `FDD_5_Dry_Run/runtime/` | temporary failure fixtures (deleted after use, git-ignored) |

Reports are timestamped and never overwritten. Paths in reports are redacted to `<repo>` / `~`.

## Stage A — Environment readiness (automatic)
Python ≥ 3.11 · required imports (fastapi, uvicorn, pydantic, torch, ultralytics, cv2, numpy, psutil, yaml,
reportlab, pypdf) · optional imports (streamlit, openvino) · `Backend/best.pt` SHA256 · OpenVINO export ·
watchdog config · taxonomy · camera config · ports 8000/8501 free · writable data/runtime dirs · disk ·
Playwright + Microsoft Edge · approved samples `tests/assets/ife_ui3_textile.png`, `tests/assets/ife_ui3_fire.png` ·
ffmpeg (optional: recording only). Nothing is installed or downloaded; a missing item is reported as `FAIL`.

## Stage B — Startup
1. `EAP_5_Watchdog start` (validates config and model checksum before launching).
2. Wait (≤ 240 s) until the watchdog reports both services healthy: backend `/health` with `model_loaded: true`,
   dashboard `/_stcore/health` = `ok`.
3. FDD-3 smoke test: `/health`, a real `/predict` on the fire sample (contract + 12-class map), corrupt upload → 400,
   `/system/status`, `/incidents`, dashboard health.

## Stage C — Demo workflow (what the presenter shows)
| # | Presenter action | Expected | Recovery if it fails |
|---|---|---|---|
| C1 | Introduce IndustriX (title card / storyboard scene 1–2) | verified capabilities only | — |
| C2 | Open http://127.0.0.1:8501 | Industrial Vision Console, Live Monitor tab | `EAP_5_Watchdog status`; restart with stop/start |
| C3 | Image Inference → upload `ife_ui3_textile.png` → Detect Defects | annotated image + table `baekra 95.0%` | re-upload; if "backend is unavailable" check the sidebar URL is `http://127.0.0.1:8000` |
| C4 | Upload `ife_ui3_fire.png` → Detect Defects | `fire 81.7%, smoke 40.0%, smoke 32.5%` | as C3 |
| C5 | Live Monitor → Incident History, quality alarms, edge health | panel renders; "LOCAL ONLY — CLOUD DISABLED" | reload the page |
| C6 | Close: stop with `EAP_5_Watchdog stop` | ports freed | — |

The rehearsal checks C3/C4 by also calling `/predict` directly with the same file and requiring the dashboard
table to equal the backend output (class and rounded confidence, in order).

Not part of the live demo (not reliable in this checkout): live three-camera streaming (≈ 2.5 fps aggregate on
this CPU, needs demo media), FastAPI `/docs` (needs a public CDN), PDF export (no confirmed incident in the local
store), and any accuracy/latency/memory claim (no approved targets).

## Stage D — Failure recovery (all non-destructive)
| # | Scenario | How it is created | Expected |
|---|---|---|---|
| D1 | dashboard → backend connection failure | sidebar URL set to an unused local port in the browser session | "FastAPI backend is unavailable…", app keeps running; a reload restores the default URL |
| D2/D3 | corrupt PNG / text file uploaded | in-memory bytes | HTTP 400 "not a readable image" |
| D4 | malformed request | empty multipart body | HTTP 422 |
| D5 | inference timeout (client side) | 1 ms client timeout | timeout reported, backend stays healthy |
| D6 | missing model weights | validator pointed at a non-existent temp path (real model untouched) | `FAIL … provision the verified best.pt` |
| D7 | backend start without model | temp copy of the watchdog config with a missing model path → `validate` | refused, exit ≠ 0 |
| D8 | missing configuration value | temp config without `services` → `validate` | `CONFIG INVALID`, exit 2 |
| D9 | recording failure | FDD-4 recorder preflight with ffmpeg hidden | refused with install hint |
| D10 | backend unreachable | readiness probe on an unused port | connection error reported, no crash |
| D11 | backend crash | kill of the **watchdog-owned** backend process tree only | watchdog restarts it; `/predict` works again |
| D12 | graceful shutdown and restart | `stop` → ports free → `start` → smoke 6/6 → `stop` | clean restart |

Network-dropout testing does not apply: the workflow uses loopback only.

## Offline verification (level achieved)
- The browser runs with a guard that aborts every non-loopback request and records it.
- The backend process tree's sockets are sampled every 2 s for non-loopback remote endpoints.
- The watchdog starts the backend with `YOLO_OFFLINE=true`, `YOLO_AUTOINSTALL=false`; the model is a local file
  verified by SHA256 and never downloaded.
- **Not verified:** physical network isolation (the adapter was not disabled). Do this once on the Demo Day
  laptop: disconnect Wi-Fi/Ethernet, run the full rehearsal, reconnect.

## Resources
RSS of the backend process tree and system CPU are sampled every 2 s during the run and stored in the report
(observations only; no approved memory or latency threshold exists). The "memory drift < 5 %" criterion is
**not verified** by a few-minute rehearsal; see the EAP-4 load/memory profile for long-run behaviour.

## Results of the official dry run (2026-10-22)
See `reports/fdd5/FDD_5_Review.md` for the executed run, its timings and evidence. The first execution
(log `reports/fdd5/rehearsal_terminal_run1.txt`) was also READY but measured only the venv launcher's memory
(≈ 5 MiB) instead of the interpreter; the sampler was fixed to sum the process tree and the rehearsal was rerun.

## Immediately before Demo Day
1. Laptop on mains power; close other heavy applications (the capture showed system CPU near 100 % under load).
2. `git status` clean on the agreed revision; `Backend/best.pt` present.
3. Run `& $py -m FDD_5_Dry_Run.rehearse` → must print `REHEARSAL: READY`.
4. Physically disconnect the network and run it again (closes the open offline item).
5. `& $py -m EAP_5_Watchdog start`, open the dashboard, keep the FDD-4 MP4 ready as a fallback.
