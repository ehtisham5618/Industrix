**Objective:** a repeatable, evidence-producing Demo Day dry run of the real IndustriX product (FDD-5).

**Implementation**
- `FDD_5_Dry_Run/rehearse.py` (`python -m FDD_5_Dry_Run.rehearse [--preflight-only] [--skip-ui] [--skip-restart]`) runs four stages:
  - A, readiness: reuses the FDD-3 validator.
  - B, startup: EAP-5 watchdog plus the FDD-3 smoke test.
  - C, workflow: dashboard inference in headless Edge on the approved samples, compared with a direct `/predict`.
  - D, recovery: 12 non-destructive scenarios, including crash auto-restart and clean restart.
- It writes a timestamped Pydantic report (PASS / FAIL / BLOCKED / NOT VERIFIED), screenshots, resource samples and offline observations. It never overwrites a report, refuses busy ports, and stops its services on exit or Ctrl+C.
- `docs/demo/DEMO_DAY_DRY_RUN.md`: commands, stages, recovery table, offline level, pre-Demo-Day checklist.
- 21 tests, CI job `demo-dry-run`, README section. No application or model changes.

**Actual dry run (2026-10-22 18:26–18:28 UTC):** READY, 59/59 PASS. Report: `reports/fdd5/rehearsal/rehearsal_20261022T182610Z.json`.
- Services healthy in 22.2 s.
- Dashboard results equal to the backend: textile baekra 95.0%; fire 81.7%, smoke 40.0% and 32.5%.
- Backend crash: auto-restart healthy in 12.0 s.
- Clean restart: healthy in 20.2 s, smoke test 6/6.
- 0 non-loopback requests or sockets.

**Tests:** FDD-5 21 passed; flake8 clean; full suite 683 passed, 2 failed (pre-existing ESE-CPU1 INT8 gates), 12 skipped.

**Not verified:**
- physical network isolation
- memory drift < 5% (not measurable in a few minutes)
- a human presenter walk-through on the Demo Day laptop
- GitHub Actions (never run on this repo)
