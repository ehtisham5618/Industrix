# EAP-2 — Automated CI Model Regression Test Suite

Detects regressions in the production detector (`Backend/best.pt`,
`cme-opt2-focal-cosine-12class-v1`) across artifact integrity, class map, the real
`POST /predict` output contract, golden predictions, test-split quality metrics,
CPU latency and memory. Code: `EAP_2_CI_Model_Regression/`.

## Status vocabulary
PASS (ran, met an approved criterion) · FAIL (ran, violated a criterion or broke)
· NOT_VERIFIED (artifact/baseline/dataset unavailable) · UNDEFINED_THRESHOLD
(measured, no approved criterion). NOT_VERIFIED is never promoted to PASS.

## Run
```powershell
python -X utf8 -m pytest EAP_2_CI_Model_Regression/tests -v -rsx   # unit + negative controls (+ real model if present)
$env:EAP2_REQUIRE_MODEL='1'                                         # make a missing model a failure
python -X utf8 -m EAP_2_CI_Model_Regression.runner                   # full report -> reports/eap2/regression_report.json
python -X utf8 -m EAP_2_CI_Model_Regression.runner --model path\to\candidate.pt   # or EAP2_MODEL_PATH / EAP2_DATASET_ROOT
```
Weights and datasets stay out of Git; point `EAP2_MODEL_PATH` / `EAP2_DATASET_ROOT` at local copies.

## Baseline
`baselines/cme-opt2-focal-cosine-12class-v1.json`: SHA256 `c4aba081…0061`, exact
12-class map (water leak and chemical hazard distinct; no "chemical leak" class
exists), test-split fingerprint (image+label hashes), evaluation settings, and
metrics from the EAP-1 measured baseline run. It is created only by the explicit
`python -m EAP_2_CI_Model_Regression.build_baseline`, which refuses to overwrite;
replacing it is a reviewed change. Golden fixtures (`golden/`) use human annotation
boxes, one per class; `reference_hit` records the accepted baseline's behaviour
(it misses `cut` and `chemical hazard`). A candidate fails a golden check only if it
loses a detection the baseline had.

## Thresholds (`thresholds.json`)
No approved regression tolerance, latency SLO or memory gate exists, so those are
UNDEFINED_THRESHOLD and deltas (percentage points) are reported. CME-OPT2 targets
(mAP50 ≥ 0.72, chemical AP50 ≥ 0.65) are listed as non-enforced references. Set a
value and `"enforce": true` once approved.

## CI
`.github/workflows/model-regression.yml` (no CI existed before): syntax check,
registry validation, gate tests and a report artifact. Hosted CI has no weights,
so real-model checks are NOT_VERIFIED there and must be run on a machine holding
the verified artifacts until an artifact-delivery mechanism exists.

## Known limitations
No physical offline test (socket guards only); CPU latency is a developer-laptop
measurement; `/predict` returns an unhandled error on corrupt uploads (strict
xfail test documents it); the workflow has not yet run on GitHub.
