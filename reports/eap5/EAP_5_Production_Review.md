# EAP-5 — Auto-Restart Watchdog Daemon & Setup Script: Production Review

**Status: IMPLEMENTED — REVIEW BLOCKED** (implementation and tests complete; GitHub CI has
not run, physical offline and long-duration memory stability are not verified).

## What is monitored
| Service | Launch (owned by the watchdog) | Health check |
|---|---|---|
| backend | `{python} -m uvicorn Backend.main:api_app --host 127.0.0.1 --port 8000` | `GET /health` → 200 and `model_loaded: true` (existing EAP-3 endpoint) |
| dashboard | `{python} -m streamlit run Frontend/app.py --server.address 127.0.0.1 --server.port 8501` | `GET /_stcore/health` → `ok` (Streamlit built-in) |
No new endpoints were added. Inference, model and UI code are unchanged.

## Live recovery on the real services (Windows 11)
| Run | Failure | Detection → restart | Verified recovery | Shutdown |
|---|---|---|---|---|
| Foreground | killed backend PID 20868 (+child) | next tick; restart 0.02 s later (PID 14456) | 21.3 s, by `/health` | owned processes gone, ports free; stops were **forced** → fixed (below) |
| Background (`start`, PID 8356) | killed backend PID 13156 at 06:45:32 | restarted as PID 3248 | 06:45:47, by `/health` | **graceful**: dashboard exit 0, backend exit 3 in 0.4 s; ports free |
The dashboard stayed healthy and was never restarted in either run. Events: `live_background_watchdog_events.jsonl`.

## Soak (watchdog process, disposable supervised service)
| Item | Result |
|---|---|
| Duration | 3,595 s of 3,600 (completed), 670 samples every 5 s, 300 s warm-up |
| Injected failures | 58 (29 crashes, 29 unhealthy spells) |
| Restarts / verified recoveries | 58 / 58; 0 recovery failures; 0 circuit opens |
| Health checks | 1,803 |
| RSS | baseline 39.47 MB → end 39.78 MB: **+0.80%** (strict < 5%) **PASS**; peak 39.86 MB |
| Private committed bytes | 27.04 MB → 27.04 MB: **0.00% PASS** |
| Handles / threads / children | 151 → 151 / 2 → 2 / max 1 |
| Event buffer | reached its 256 limit and stayed bounded |
| Leftover processes | none; watchdog exit 0 |

RSS window medians: 39.47, 39.48, 39.58, 39.67, 39.78, 39.78 MB, a ~0.3 MB rise then a
plateau. Private bytes did not grow. The RSS Theil–Sen slope (+0.51 MB/h, projected
+30.9 %/24 h) would be flagged by the EAP-4 trend criterion, so **long-duration memory
stability is NOT VERIFIED** by one hour; a multi-hour soak is recommended.
No absolute memory ceiling or watchdog latency SLA is defined; none is invented.

## Tests
| Suite | Result |
|---|---|
| `python -m pytest EAP_5_Watchdog/tests -v -rs` (Windows, Python 3.14) | **38 passed** |
| Same suite in a Debian Linux container (Python 3.12, POSIX process groups) | **37 passed, 1 skipped** (PowerShell-only test) |
| Repository suite (ESE-CPU1 venv, EAP-3/EAP-4 excluded) | 545 passed, 2 failed (inherited ESE-CPU1 gates) |
| Org lint gate (flake8 E9,F63,F7,F82) / compileall | 0 findings / OK |
| Setup | PowerShell `validate` + `check` ×2 PASS; `sh -n` PASS; Linux install/check/repeat/validate PASS |

## Defects found and fixed during validation
1. Windows: CTRL_BREAK never reached children started with `CREATE_NO_WINDOW` → every stop was forced. Children now share the watchdog's console; background mode gets its own hidden console; stop mode is logged.
2. A concurrent reader of `status.json` made `os.replace` fail on Windows and **crashed the watchdog**; the write now retries and records `status_write_failed` instead.
3. Log handlers were only closed by `run()`, leaking file handles; `close()` added.
4. The first soak attempt had a relative-path bug in the soak tool (no failures reached the service); it was discarded and rerun.

## Not verified / limitations
- GitHub Actions run (Actions inactive on the repository).
- Physical network disconnection (offline is enforced by loopback-only URLs, a socket guard test and import inspection).
- Real backend/dashboard under the watchdog on Linux (the watchdog core and setup script were verified there).
- Multi-hour/multi-day memory stability.
- No native service-manager (systemd/Windows Service) installation; foreground/background launcher only.
