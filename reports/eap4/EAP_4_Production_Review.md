# EAP-4 — Continuous Load Test & Memory-Leak Profile: Production Review

**Status: IMPLEMENTED — REVIEW BLOCKED.**
A **4-hour** run of the six-hour profile was performed and stopped early by decision.
The six-hour requirement is **not met**. The 4-hour evaluation **FAILS** the
private-bytes memory-trend gate (slow sustained growth), so stability is not demonstrated.

## Run
| Item | Value |
|---|---|
| Run ID | `20261020T212619Z-six-hour` |
| Target | real `POST /predict`, `Backend/best.pt` (SHA256 `c4aba081…0061`), uvicorn, Python 3.12, loopback |
| Configured / actual duration | 21,600 s / **14,400 s** (02:26:19 → 06:26:29 PKT) |
| Stop | Watcher stopped the harness at 14,400 s (`four_hour_stop_record.json`); data recovered from `summary.partial.json` |
| Load | 2 closed-loop workers (max 2 in flight), 30 s timeout, 600 s warm-up excluded |
| Host | i5-7200U 2C/4T, 15.9 GB RAM, Windows 11, **shared** (Chrome/VS Code open; system CPU mean 88.5%) |

Status of the same data under each framing:
- Six-hour profile (`summary.reanalyzed.json`): **INTERRUPTED**; run_completed NOT_VERIFIED.
- 4-hour evaluation (`summary.evaluated_14400s.json`, labelled `original_requirement_met: false`): **FAIL**.

## Requests and latency (steady state, 30,401 requests)
- Successful 30,400 · failed 1 (one connection error) · timeouts 0 · error rate 0.0033% · all responses HTTP 200
- Throughput 2.20 req/s (+1,068 warm-up requests; 31,469 total)
- Latency of successful requests (ms, client-observed, log-bucket histogram ≤ 1% error):
  mean 907.6 · p50 794.7 · p90 1,497.6 · p95 1,789.7 · p99 2,408.7 · max 22,863.3
- No approved latency or error-rate SLA exists → those gates are UNDEFINED_THRESHOLD.

## Memory
| Measure | Baseline (median 600–2,400 s) | End (median last 1,800 s) | Drift | Gate (< 5%) | Trend |
|---|---:|---:|---:|---|---|
| RSS (Windows working set) | 450.7 MB | 362.9 MB | −19.48% (−87.8 MB) | PASS | no growth: one drop at ~1.4 h, then flat |
| **Private committed bytes** | 593.8 MB | 600.3 MB | +1.10% (+6.5 MB) | PASS | **FAIL: rises in 5/5 window steps (595.0 → 595.6 → 595.9 → 598.3 → 599.6 → 599.8 MB), Theil–Sen +1.51 MB/h, projected +6.1% of baseline per 24 h** |

- Startup RSS 387.9 MB; RSS peak 494.7 MB at 1,194 s; private-bytes peak 608.8 MB at 6,660 s.
- The RSS drop was not memory pressure (≈ 5 GB stayed available): Windows trimmed the
  working set. RSS alone would have reported a misleading pass, so the harness now
  gates private bytes on Windows as well.
- The leak criterion (≥ 5% projected per 24 h, or every window rising with > 1% growth)
  was committed in `86b6b46` **before** the run was analysed. Growth is small
  (~1.5 MB/h) but sustained; a full 6-hour or longer run is needed to confirm or rule it out.
- A drift below 5% is not proof that no leak exists (it does not here).

## Other resources
Handles 472 → 474 (+2) · threads 8 → 8 · child processes 0 · service CPU mean 248.6%
(≈ 2.5 logical cores) · harness RSS 49 → 52 MB · 1,436 profiler samples, 0 failures,
0 gaps, 0 restarts.

## Gates (4-hour evaluation)
run_completed PASS (4 h only) · memory_drift (RSS) PASS · memory_trend (RSS) PASS ·
memory_drift_private_bytes PASS · **memory_trend_private_bytes FAIL** · service_restarts PASS ·
telemetry_continuity PASS · error_rate / p95_latency / memory_ceiling / handle & thread growth UNDEFINED_THRESHOLD.

## Tests
`python -m pytest EAP_4_Load_Test/tests -v -rs` with `EAP4_TARGET_URL=http://127.0.0.1:8000`:
**43 passed** (includes the real-service smoke). Org lint gate: 0 findings.

## Changes after the run started
The harness/service source used by the run is hashed in `six_hour_source_snapshot.json`.
Afterwards only analysis-side code changed (no load/profiling change): an external stop
hook for tests, recovery of terminated runs, a labelled shorter-duration evaluation, and
the private-bytes gates. Re-analysis reads the unchanged recorded samples.

## Blockers
1. Six-hour run not completed (4 h by decision).
2. Private-bytes growth (~1.5 MB/h) must be investigated; run ≥ 6 h to confirm.
3. No approved latency/error-rate SLA or memory ceiling.
4. Shared developer laptop, not gateway hardware; `/predict` serialises requests (async endpoint, blocking inference).
5. GitHub Actions has not run on the repository.
