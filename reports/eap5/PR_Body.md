Local-first watchdog for the FastAPI backend and Streamlit dashboard.

**What changed**
- `EAP_5_Watchdog/`: Pydantic v2 config/contracts, loopback health checks (backend `/health` + `model_loaded`, Streamlit `/_stcore/health`), restart policy (threshold, cooldown, capped exponential backoff, rolling budget → degraded circuit), verified recovery, duplicate-port + single-instance protection, owned-process-only graceful shutdown, bounded events, rotated logs, CLI (`validate`/`run`/`start`/`status`/`stop`), soak tool, 38 tests
- Setup scripts: `scripts/setup_watchdog.ps1` (Windows) and `scripts/setup_watchdog.sh` (Linux POSIX sh)
- CI: `watchdog` job in `model-regression.yml`; runbook `docs/EAP_5_Auto_Restart_Watchdog.md`

**Evidence**
- Real services: killed backend restarted and only marked recovered after `/health` succeeded (21.3 s / 15 s); dashboard unaffected; graceful stop, ports freed.
- 60-minute soak: 58 injected failures → 58 restarts → 58 verified recoveries; watchdog RSS +0.80%, private bytes 0.00% (strict < 5%); handles/threads flat; event buffer bounded.
- Tests: Windows 38/38; Linux container 37 passed + 1 Windows-only skip; repository 545 passed / 2 inherited CPU1 failures.

**Not verified:** GitHub Actions run, physical network disconnection, multi-hour memory stability (RSS has a small early rise then plateau), real services under the watchdog on Linux. No absolute memory ceiling or latency SLA exists.

Evidence: `reports/eap5/EAP_5_Production_Review.md`, `reports/eap5/eap5_summary.json`, `reports/eap5/soak/`.
