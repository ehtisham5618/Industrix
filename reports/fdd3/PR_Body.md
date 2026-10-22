Production runbook and deployment handoff package for the system as it exists, with every quick-start command executed.

**What changed**
- `docs/deployment/`: `PRODUCTION_RUNBOOK.md` (Mermaid architecture, start/stop, readiness, logs, monitoring sources and gaps), `DEPLOYMENT_GUIDE.md` (tested/unverified/unsupported modes, install, configuration reference for every runtime variable, model provisioning, offline, verification checklist), `TROUBLESHOOTING.md`, `ROLLBACK_AND_RECOVERY.md`, `DEPLOYMENT_HANDOFF.md`
- `FDD_3_Deployment_Handoff/`: `validate_deployment` (read-only preflight) and `smoke_test` (live loopback checks), 17 tests that keep documented env vars, endpoints, scripts and paths consistent with the code; CI job `handoff-docs`

**Executed:** preflight 24/24 PASS → watchdog start → ready in 23 s → smoke 6/6 PASS (real `/predict`, corrupt upload 400, incidents, dashboard) → graceful stop in 2 s with ports freed; rollback DB backup verified (integrity ok); FDD-3 tests 17/17; repository 644 passed / 2 baseline CPU1 failures.

**Not verified / open:** physical offline, Linux native services, GPU, target hardware, GitHub Actions; inherited blockers (EAP-4 memory growth, ESE-CPU1 INT8 gates, no SLAs). No application, model or dependency changes.

Evidence: `reports/fdd3/FDD_3_Review.md`, `reports/fdd3/fdd3_summary.json`.
