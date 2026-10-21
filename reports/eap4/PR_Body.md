Continuous load-test harness and service memory profiler for the real `POST /predict`.

**Run performed: 4 hours (14,400 s) of the six-hour profile, stopped early by decision. The six-hour requirement is not met.**

**Results (steady state):** 30,401 requests, 1 connection error (0.0033%), 2.20 req/s; latency p50 795 ms, p95 1,790 ms, p99 2,409 ms.

**Memory:** RSS drift −19.5% (Windows working-set trim, not a real reduction). Private committed bytes +1.10% (passes < 5%) but rise in 5/5 windows at ~1.5 MB/h, projected +6.1%/24 h → **trend gate FAIL**: a possible slow leak that a full-duration run must confirm.

**What changed**
- `EAP_4_Load_Test/`: config/profiles (six-hour opt-in via `--confirm-long-run`), closed-loop load generator (bounded in-flight, timeouts, EAP-2 contract validation), JSONL service profiler, drift gate + Theil–Sen trend analysis (RSS and Windows private bytes), partial-run recovery, `--analyze` and labelled shorter-duration evaluation, Markdown report, 43 tests
- CI: `load-harness` job in `model-regression.yml` (never runs the long test)
- Runbook: `docs/EAP_4_Load_Test_Memory_Profile.md`

**Not verified:** six-hour duration; GitHub Actions run; physical network disconnection. No approved latency/error-rate SLA exists.

Evidence: `reports/eap4/EAP_4_Production_Review.md`, `reports/eap4/eap4_summary.json`, `reports/eap4/runs/20261020T212619Z-six-hour/`.
