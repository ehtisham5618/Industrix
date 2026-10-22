# FDD-1 — Code Freeze & Full System Regression Pass

## Freeze baseline
- Baseline commit: `9759dc0` (EAP-5 evidence; tip of the stacked Sprint 3 branches, PRs #1–#19 open)
- Branch: `feature/sprint4-fdd1-code-freeze-regression`; working tree clean at freeze.
- FDD-1 changes are limited to regression tests, the release-gate runner, a CI job and documentation.
  No application code, model weights, class maps, thresholds or dependencies were changed.

## Environment
Windows 11, Intel i5-7200U (2C/4T), 15.9 GB RAM, no GPU. Full-stack interpreter:
`ESE_CPU1_Quantization/runtime/venv` (Python 3.12.9, torch 2.10.0+cpu, ultralytics 8.4.24,
FastAPI 0.143.0, Streamlit 1.65.0, OpenVINO 2026.4.1). Model: `Backend/best.pt`
SHA256 `c4aba081…0061` (12 classes, verified); OpenVINO INT8 and ONNX FP16 exports present.

## Commands
```powershell
$py = 'ESE_CPU1_Quantization/runtime/venv/Scripts/python.exe'
& $py -m pytest -q -rs --junitxml=reports/fdd1/baseline/junit_baseline.xml        # baseline (before changes)
& $py -m pytest FDD_1_Release_Regression/tests -v -rs                              # FDD-1 gap tests
& $py -m FDD_1_Release_Regression.run_release_gate                                # full release gate
#   --skip-live / --skip-model / --load-seconds N
```
The gate writes `reports/fdd1/release_regression.json` and `.md`.

## What the gate runs
| Stage | Coverage |
|---|---|
| `full_test_suite` | every repository test (pytest + JUnit), compared test-by-test with the baseline JUnit; new failures are `FAIL`, pre-existing ones `BASELINE_FAILURE` |
| `model_regression` | EAP-2 runner on the real checkpoint: hash, class map, real `/predict` contract, golden fixtures, test-split metrics vs the approved baseline manifest |
| `live_stack_startup` | real backend + dashboard launched and health-verified by the EAP-5 watchdog |
| `live_predict_contract` | real `POST /predict` on both fixtures, validated against the EAP-2 contract and class map |
| `live_corrupt_upload` | corrupt image → HTTP 400 |
| `live_service_endpoints` | `/health`, `/system/status`, `/incidents`, Streamlit `/_stcore/health` |
| `live_dashboard_render` | Streamlit `AppTest` renders `Frontend/app.py` against the live backend with no exception / unavailable error |
| `load_and_memory_smoke` | EAP-4 smoke load on the live backend: requests, errors, latency, RSS/private-bytes drift (short: NOT_VERIFIED for stability) |
| `no_unexpected_restarts_during_gate` | watchdog restart counters stay 0 under the gate's traffic |
| `clean_shutdown` | watchdog exits 0 and ports 8000/8501 are released |
| `physical_offline` | always NOT_VERIFIED (no physical disconnection performed) |

New tests in `FDD_1_Release_Regression/tests/`: `/predict` 422 for a missing/misnamed field, 400 for
empty, text, corrupt JPEG uploads; 503 from `/predict` and `/health` without a model; request
isolation and repeatability; dashboard↔backend field compatibility; fail-fast startup on a missing
model and on a checksum mismatch; optional-model startup degrades to 503; dashboard renders with the
backend down; runtime entry points import no cloud inference clients and keep the offline policy.

## Status vocabulary and interpretation
PASS · FAIL (new failure, release blocker) · BASELINE_FAILURE (failed identically before FDD-1) ·
BLOCKED (prerequisite missing, e.g. Docker images) · NOT_VERIFIED (insufficient evidence).
Overall `PASS_WITH_EXCEPTIONS` means no new failure but some items are baseline failures, blocked or
not verified; it is not a clean release pass.

## Known baseline failures and limitations
- ESE-CPU1 `test_actual_ir_size_below_6_5_decimal_mb` and `test_actual_map_drop_below_one_percentage_point`
  (genuine measured gate failures of the INT8 export, pre-existing).
- EAP-3 container tests are BLOCKED: Docker images were removed to free disk space.
- No approved latency/error-rate SLA or absolute memory ceiling; the gate reports measurements only.
- Memory stability: see EAP-4 (4-hour run, private-bytes trend flagged) and EAP-5 (1-hour watchdog soak);
  the gate's smoke load cannot establish stability.
- GitHub Actions has not run on the repository; CI jobs are configured but unverified.
- Physical offline operation not tested.

## Release-gate checklist
See `reports/fdd1/FDD_1_Release_Readiness.md` for the filled-in checklist and results.
