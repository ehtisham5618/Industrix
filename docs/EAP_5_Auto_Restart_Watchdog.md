# EAP-5 — Auto-Restart Watchdog Daemon & Setup Script

Local-first supervisor for the IndustriX services that exist in this repository:
the FastAPI inference backend (`uvicorn Backend.main:api_app`, port 8000) and the
Streamlit dashboard (`Frontend/app.py`, port 8501). Code: `EAP_5_Watchdog/`.
It is an operational component only: it does not change inference, models or the UI.

## Architecture
| Module | Responsibility |
|---|---|
| `config.py` | Pydantic v2 config, bounds, placeholder expansion (`{python}`, `{root}`, `{env:NAME}` only), runtime validation |
| `contracts.py` | Typed records: health result, event, service status, watchdog status |
| `health.py` | Loopback HTTP check (status / exact body / JSON field must be `true`, hard timeout, capped body) and process liveness |
| `policy.py` | Failure threshold, cooldown, capped exponential backoff, rolling restart budget |
| `process.py` | Owned child processes (`shell=False`, own process group, rotated output log), single-instance lock |
| `supervisor.py` | Tick loop, per-service state machine, events, status file, graceful shutdown |
| `__main__.py` | CLI: `validate`, `run`, `start`, `status`, `stop` |
| `soak.py` | Resource soak of the watchdog with injected failures |

Health checks reuse what the services already expose: backend `GET /health`
(EAP-3; 200 only when the model is loaded; the watchdog also requires
`model_loaded: true`) and Streamlit's built-in `GET /_stcore/health` (`ok`). No
new endpoints were added.

## State machine
`starting` (failures ignored during `startup_grace_seconds`, except a process exit)
→ `healthy` ⇄ `unhealthy` (consecutive failures counted) → at `failure_threshold`:
restart if the policy allows, else `backoff` → `recovering` (marked recovered **only**
after a successful health check within `recovery_timeout_seconds`; otherwise
`recovery_failed` and the policy decides again) → `healthy`.
When `max_restarts` restarts happened within `window_seconds` the service is
`degraded` (circuit open): no restarts, still health-checked; if it becomes healthy
on its own it returns to `healthy`; when the window frees capacity a single
half-open restart is attempted. `blocked`: the service port is owned by a process
this watchdog did not start; it is never killed and no duplicate is started.
`config_error`: the executable/cwd/placeholder could not be resolved. One service's
state never stops the others from being monitored.

Backoff before restart *n* (n ≥ 2) is `max(cooldown, min(initial × multiplier^(n−2), max))`;
it resets after the service stays healthy for `recovery_timeout_seconds`. The
rolling budget does not reset early.

## Configuration (`EAP_5_Watchdog/configs/watchdog.json`)
| Key | Default | Bounds / rule |
|---|---|---|
| `tick_seconds` | 1.0 | 0.1–60 |
| `event_buffer` | 256 | 16–10 000 events kept in memory (deque) |
| `log_max_bytes` / `log_backups` | 5 MB / 3 | rotating `watchdog.jsonl` |
| `child_log_max_bytes` | 20 MB | per service output; rotated at each (re)start |
| service `command` | — | argument list, `shell=False`; executable must resolve |
| service `port` | — | used to refuse duplicates |
| `health.kind` / `url` | `http` | URL must be `http://` on loopback |
| `health.timeout_seconds` | 5 | 0–60 |
| `interval_seconds` | 10 | 0.2–3600 |
| `startup_grace_seconds` | 60–90 | 0–3600 |
| `stop_timeout_seconds` | 15–25 | graceful stop before kill |
| `restart.failure_threshold` | 3 | 1–100 |
| `restart.cooldown_seconds` | 15 | 0–3600 |
| `restart.backoff_initial/max_seconds`, `multiplier` | 10 / 300, ×2 | max ≥ initial |
| `restart.max_restarts` / `window_seconds` | 5 / 3600 | rolling budget |
| `restart.recovery_timeout_seconds` | 90–120 | time for a restart to become healthy |
`env` values are passed to the child and never logged (secret-looking names are
redacted, others shown as `<set>`). Override the config path with
`INDUSTRIX_WATCHDOG_CONFIG` or `--config`.

## Setup and commands
Supported: **Windows 10/11 with PowerShell 5.1+** (validated) and **Linux with POSIX sh**
(script syntax-checked; see Platform support). Python 3.11+.
```powershell
powershell -ExecutionPolicy Bypass -File EAP_5_Watchdog/scripts/setup_watchdog.ps1 -Action check     # deps only
powershell -ExecutionPolicy Bypass -File EAP_5_Watchdog/scripts/setup_watchdog.ps1 -Action validate  # + config/model
powershell -ExecutionPolicy Bypass -File EAP_5_Watchdog/scripts/setup_watchdog.ps1 -Action start     # background
python -m EAP_5_Watchdog status
python -m EAP_5_Watchdog stop
python -m EAP_5_Watchdog run          # foreground (Ctrl+C stops it and the services it owns)
```
```sh
sh EAP_5_Watchdog/scripts/setup_watchdog.sh validate     # PYTHON=..., CONFIG=..., INSTALL=1
sh EAP_5_Watchdog/scripts/setup_watchdog.sh start
```
The scripts pick an interpreter (explicit → active venv → PATH), require Python
3.11+, check `pydantic`/`psutil`, report missing service dependencies, and install
only with `-Install`/`INSTALL=1` and only into a virtual environment unless
`-AllowGlobalInstall`/`ALLOW_GLOBAL_INSTALL=1`. `validate` checks executables,
working directories, placeholders and the local model file + SHA256 (no
download). Re-running is safe. No system service is installed and startup
settings are not changed; `start` runs a detached background process (on Windows
with its own hidden console so it can deliver CTRL_BREAK to its children).

## Files (`EAP_5_Watchdog/runtime/`)
`status.json` (current state, rewritten atomically every tick) · `watchdog.jsonl`
(structured events: `ts`, `monotonic_s`, `event`, `service`, `state`, `reason`,
`outcome`, `pid`, `restart_count_window`, …) · `logs/<service>.out.log` (+ `.1`) ·
`watchdog.lock` · `watchdog.stop` (stop request) · `watchdog.console.log` (background mode).

## Safety
- Only processes the watchdog started (and their descendants) are signalled; a
  recycled PID is detected by process start time. Nothing is matched by name.
- Shutdown: CTRL_BREAK (Windows) / SIGTERM to the child's own process group (POSIX),
  then kill after `stop_timeout_seconds`. Each stop is logged as `graceful`,
  `forced` or `already_exited`.
- A second watchdog refuses to start (exit code 3); a stale lock from a dead
  watchdog is reclaimed; the holder is never terminated.
- No cloud calls, telemetry or downloads; health URLs must be loopback.

## Troubleshooting
| Symptom | Meaning / action |
|---|---|
| `blocked` | Another process owns the port. Stop it (or the other watchdog) yourself; the watchdog will not. |
| `config_error` | Executable or working directory missing; run `validate`. |
| `degraded` | Restart budget exhausted. Inspect `logs/<service>.out.log`; restarts resume when the window frees capacity, or stop/start the watchdog. |
| `recovery_failed` events | The service restarted but never became healthy within the recovery timeout (e.g. model missing → backend exits). |
| `status_write_failed` events | Something held `status.json` open; monitoring continues. |
| exit code 3 | Another watchdog is running (`python -m EAP_5_Watchdog status`). |

## Tests and soak
```powershell
python -m pytest EAP_5_Watchdog/tests -v -rs
python -m EAP_5_Watchdog.soak --duration 3600 --chaos-interval 60 --out reports/eap5/soak
```
The soak runs the real watchdog as a separate process supervising a disposable
service while crashes and unhealthy spells are injected, and samples the
watchdog's RSS, private bytes (Windows), handles, threads, children and event
buffer. Drift = (end-window median − baseline median) / baseline × 100, strict
< 5% with ≥ 3 samples per window. No absolute memory ceiling is approved.

## Known limitations
- Linux execution is covered by the CI job and script syntax; it was not run on a Linux host in this delivery.
- No native service-manager (systemd / Windows Service) installation is provided.
- Health checks are sequential; a hung check delays others by at most its timeout.
- Physical network disconnection was not tested; offline behaviour is verified by loopback-only URLs, a socket guard in the integration test and import inspection.
