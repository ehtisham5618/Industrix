Code-freeze regression pass over the frozen Sprint 3 code (baseline `9759dc0`). Tests, release tooling, CI and docs only: no application code, model, threshold or dependency changes.

**Release gate** (`python -m FDD_1_Release_Regression.run_release_gate`, full-stack venv):
- Full suite: 606 passed / 2 failed / 12 skipped; both failures are **baseline failures** (ESE-CPU1 INT8 size and mAP-drop gates). Baseline before changes: 593 / 2 / 11.
- Real-model regression PASS: mAP50 78.20% (+0.03 pp vs approved baseline), mAP50-95 49.17% (−0.02 pp).
- Live backend + dashboard under the EAP-5 watchdog: startup, `/predict` contract on both fixtures, corrupt upload → 400, `/health` `/system/status` `/incidents` `/_stcore/health` → 200, Streamlit AppTest render, no restarts, clean shutdown: all PASS.
- Load smoke 180 s: 321 requests, 0 errors, p50 860 ms, p95 2,097 ms; private bytes +7.5% (short run, NOT VERIFIED).

**New tests** (`FDD_1_Release_Regression/tests`): `/predict` 422/400/503 paths, request isolation, dashboard↔backend field compatibility, fail-fast and checksum startup, dashboard render with backend down, offline import checks. CI job `release-regression` added.

**Release blockers (not fixed here):** possible backend memory growth (EAP-4 trend + this smoke), ESE-CPU1 INT8 gates, Docker tests blocked, GitHub Actions never run, no approved SLAs, physical offline untested.

Evidence: `reports/fdd1/FDD_1_Release_Readiness.md`, `reports/fdd1/release_regression.json`.
