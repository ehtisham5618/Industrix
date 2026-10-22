# FDD-1 — Code Freeze & Full System Regression: Release Readiness

**Final status: IMPLEMENTED — REVIEW BLOCKED.** No new regression was found in the frozen code,
but release blockers remain (see below). This is not a green release.

## Code freeze
- Baseline: `9759dc0` (clean tree) on `feature/sprint4-fdd1-code-freeze-regression`; FDD-1 implementation `88bf3e3`.
- Changes: tests, release-gate runner, CI job, docs only. No application code, model weights,
  class maps, thresholds or dependencies changed. `Backend/best.pt` SHA256 `c4aba081…0061` unchanged.

## Results (gate run 21:58 → 22:09 PKT, full-stack venv Python 3.12.9)
| Stage | Status | Evidence |
|---|---|---|
| Full test suite | 606 passed, 2 failed, 12 skipped (620) | both failures are **baseline failures** (ESE-CPU1 INT8 size and mAP-drop gates); baseline before changes: 593 passed, 2 failed, 11 skipped |
| Model regression (real checkpoint) | PASS | 16 checks PASS; mAP50 78.20% (Δ +0.03 pp vs approved baseline), mAP50-95 49.17% (Δ −0.02 pp); 8 measurements have no approved tolerance |
| Live stack startup (EAP-5 watchdog) | PASS | backend + dashboard healthy in 14.1 s |
| Live `/predict` contract | PASS | fire fixture: 3 detections (fire, smoke); textile fixture: 1 (baekra); contract + class map valid |
| Corrupt upload | PASS | HTTP 400 "Uploaded file is not a readable image." |
| Service endpoints | PASS | `/health`, `/system/status`, `/incidents`, Streamlit `/_stcore/health` all 200 |
| Dashboard render (Streamlit AppTest, live backend) | PASS | no exception, no "backend unavailable" error |
| Load / memory smoke (EAP-4, 180 s, 2 workers) | NOT VERIFIED | 321 requests, 0 failed, 2.00 req/s, p50 860 ms, p95 2,097 ms; RSS +3.74%, **private bytes +7.54%** (includes warm-up; too short for a drift verdict) |
| No restarts under gate traffic | PASS | backend 0, dashboard 0 |
| Clean shutdown | PASS | watchdog exit 0; ports 8000/8501 freed |
| Physical offline | NOT VERIFIED | loopback-only config, socket-guard tests and import checks only |

Per component (passed/failed/skipped): CME-OPT1 12/0/0 · CME-OPT2 6/0/0 · Confidence_Calibration 7/0/0 ·
EAP-1 41/0/0 · EAP-2 29/0/0 · EAP-3 6/0/10 (Docker BLOCKED) · EAP-4 42/0/1 · EAP-5 38/0/0 ·
ESE-CPU1 14/2/0 · FDD-1 13/0/1 · IFE-UI1 21/0/0 · IFE-UI2 22/0/0 · QCI-3 67/0/0 · QCI-4 49/0/0 ·
QCI-5 42/0/0 · SED-1 28/0/0 · SED-2 35/0/0 · SED-3 23/0/0 · tests/ 111/0/0.

## Release blockers
1. **Possible slow memory growth in the backend** (EAP-4: private bytes +1.5 MB/h over 4 h, trend gate FAIL;
   FDD-1 smoke: private bytes +7.5% in 3 min). Needs investigation and a full-duration soak.
2. **ESE-CPU1 baseline failures**: INT8 artifact 11.77 MB vs < 6.5 MB gate; mAP50 drop 1.03 pp vs < 1 pp.
3. **EAP-3 container tests BLOCKED** (Docker images removed for disk space; rebuild to re-verify).
4. **GitHub Actions has never run** on the repository (all CI jobs unverified).
5. No approved latency/error-rate SLA, model-regression tolerance or memory ceiling.
6. Physical offline operation not tested; six-hour soak not completed (EAP-4 ran 4 h).

## Checklist
- [x] Baseline commit and working-tree state recorded
- [x] Dependencies and runtime environment inspected
- [x] Existing tests executed before changes (593/2/11)
- [x] Preprocessing and input validation checked (400/422/503 paths, corrupt and non-image uploads)
- [x] Model loading and inference validated (real checkpoint, contract, golden fixtures, metrics)
- [x] API contracts and error handling validated
- [x] Dashboard/backend integration checked (AppTest render live; field compatibility)
- [x] Watchdog and recovery (EAP-5 suite 38/38; live stack under the watchdog)
- [x] Alerting and incident logging (SED-2, QCI-3, IFE-UI2, QCI-5 suites; live `/incidents`)
- [ ] Offline behaviour: physical disconnection NOT VERIFIED (logical checks pass)
- [ ] Resource stability: NOT VERIFIED (open memory-growth blocker)
- [x] New regression tests pass (13 passed, 1 live-only skip, run live in the gate)
- [x] Existing failures documented as baseline failures
- [x] No unapproved model or dependency changes
- [x] Git diff reviewed
- [x] Documentation and reproducible commands updated
- [x] Branch pushed and PR opened (see PR)
