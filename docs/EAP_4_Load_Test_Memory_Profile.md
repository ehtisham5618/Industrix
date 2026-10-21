# EAP-4 — Continuous Load Test & Memory-Leak Profile

Harness: `EAP_4_Load_Test/` · Results: `reports/eap4/` · CI: `load-harness` job in
`.github/workflows/model-regression.yml` (harness tests only; never the long run).

## Architecture
`run_load_test.py` (CLI, lifecycle) → `loadgen.py` (closed-loop workers, persistent
HTTP connections, real `POST /predict`) → response validation with the EAP-2
`/predict` contract and class map → `metrics.py` (bounded counts + log-bucket
latency histogram) ‖ `profiler.py` (samples the **service** process, JSONL) →
`analysis.py` (drift gate, trend, gates) → `report.py` (Markdown). Config and
profiles: `config.py` (Pydantic v2). No new dependencies (stdlib `http.client`, psutil, pydantic).

## Prerequisites
Local `Backend/best.pt` (SHA256 `c4aba081…0061`), the test fixtures in
`tests/assets/`, and an environment with the service dependencies (the ESE-CPU1
venv, or the EAP-3 image).

## Start the service (separate process; the harness never launches it)
```powershell
$env:INDUSTRIX_MODEL_PATH='Backend/best.pt'; $env:INDUSTRIX_REQUIRE_MODEL='1'
$env:INDUSTRIX_MODEL_SHA256='c4aba081f6357e23a7370a5f7cf98eff2c6faa0c4c20a2d4dcb8bcabdd490061'; $env:YOLO_OFFLINE='true'
& ESE_CPU1_Quantization/runtime/venv/Scripts/python.exe -m uvicorn Backend.main:api_app --host 127.0.0.1 --port 8000
# or: docker run -p 127.0.0.1:8000:8000 industrix:eap3   (then add --container <name> below)
```

## Run
```powershell
python -m EAP_4_Load_Test.run_load_test --profile smoke --target-url http://127.0.0.1:8000        # 120 s
python -m EAP_4_Load_Test.run_load_test --profile short-soak --target-url http://127.0.0.1:8000   # 30 min
python -m EAP_4_Load_Test.run_load_test --profile six-hour --target-url http://127.0.0.1:8000 --confirm-long-run
python -m EAP_4_Load_Test.run_load_test --analyze reports/eap4/runs/<run_id>                       # no load
python -m EAP_4_Load_Test.run_load_test --analyze <run_dir> --evaluate-duration-seconds 14400 --stop-reason "..."
```
`--analyze` recovers a terminated run from `summary.partial.json` (reported INTERRUPTED).
`--evaluate-duration-seconds` additionally evaluates the recorded samples against a
shorter duration in a separate `summary.evaluated_<N>s.json` labelled
`original_requirement_met: false`; it can never claim the configured duration.
Any option can be overridden (`--concurrency`, `--requests-per-second`,
`--request-timeout-seconds`, `--sample-interval-seconds`, `--warmup-seconds`, …).
Runs ≥ 1 h require `--confirm-long-run`. The target must be loopback unless the
config sets `allow_remote_target`. `/health` must report `model_loaded` before load starts.

| Profile | Duration | Warm-up | Baseline / end window | Workers | Sample / report |
|---|---:|---:|---:|---:|---:|
| smoke | 120 s | 20 s | 30 s / 30 s | 2 | 2 s / 10 s |
| short-soak | 1 800 s | 120 s | 300 s / 300 s | 2 | 5 s / 60 s |
| six-hour | 21 600 s | 600 s | 1 800 s / 1 800 s | 2 | 10 s / 300 s |

## Outputs (`reports/eap4/runs/<run_id>/`)
`config.json` (effective config) · `samples.jsonl` (profiler time series) ·
`intervals.jsonl` (per-interval requests/latency) · `summary.partial.json`
(rewritten every report interval, survives interruption) · `summary.json` +
`report.md` (final). `--analyze` writes `summary.reanalyzed.json`.

## Memory methodology
- Measurement: service-process RSS (psutil); container stats added with `--container`.
- Startup: first sample after attach, reported separately.
- Baseline: **median** RSS over `[warmup, warmup + baseline_window)`.
- End: **median** RSS over the last `end_window` seconds of the actual run.
- `drift_percent = (end − baseline) / baseline × 100`; gate **PASS only if strictly < 5%**,
  with ≥ 3 valid samples in each window. Otherwise NOT_VERIFIED (never a division error or a false pass).
- Interrupted runs report the drift but the gate is NOT_VERIFIED.
- **Windows:** psutil RSS is the working set, which the OS can trim. Private committed
  bytes (psutil `vms` on Windows) get the same drift gate and trend criterion
  (`memory_drift_private_bytes`, `memory_trend_private_bytes`); on other platforms `vms`
  is virtual size and is not gated.
- Independently: peak RSS and time, optional absolute ceiling, handle/thread/child growth.
- Trend (reported separately; a sub-5% drift is not proof of no leak): Theil–Sen and
  OLS slopes over post-warm-up RSS, medians of six equal windows, rising-step count,
  peak/post-peak, RSS↔completed-requests correlation and growth per 1 000 requests.
  Declared criterion: leak suspected if every window step rises with > 1% growth,
  or the Theil–Sen slope projects ≥ 5% of baseline per 24 h.

## Latency and throughput
Latency = monotonic time from sending a request to reading the full response
(client-observed, loopback, includes multipart/HTTP overhead). Quantiles come from a
fixed log-bucket histogram (≤ 1% relative error, constant memory); p99 is withheld
below 100 samples. Warm-up requests are excluded from the steady-state summary.
Outcomes: success, http_error, invalid_response (fails the `/predict` contract), timeout, connection_error.

## Gates and status
Gate statuses: PASS, FAIL, NOT_VERIFIED, UNDEFINED_THRESHOLD. Overall status:
INTERRUPTED if the configured duration did not complete; else FAIL if any gate
failed; PASS only if **every** gate passed; otherwise NOT_VERIFIED. No latency or
error-rate SLA exists for `/predict`, so those gates are UNDEFINED_THRESHOLD and the
overall status cannot be PASS until an SLA is approved (`--max-error-rate`,
`--max-p95-latency-ms`, `--memory-ceiling-bytes`). Exit codes: 0 PASS/NOT_VERIFIED,
1 FAIL, 2 INTERRUPTED, 3 configuration/target error.

## Repeatability
Same profile, seed (fixture order), fixtures, service build and machine. Record
other load on the host: system CPU is sampled every interval. On Windows the
harness holds a temporary keep-awake request for the run so sleep cannot
interrupt it; the power plan is not changed.

## Known limitations
- `/predict` is an `async` endpoint running blocking inference, so concurrent
  requests queue on the event loop; client latency includes that queueing.
- Service GC/allocation stats are not observable from a separate process.
- Offline = loopback-only target; physical network disconnection is not exercised.
- Results from a shared developer laptop are not gateway-hardware benchmarks.
