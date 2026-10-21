# EAP-4 load test — 20261020T212619Z-six-hour

**Status: FAIL** · run state COMPLETED · profile `six-hour run evaluated as a 4-hour soak`

- Target: `http://127.0.0.1:8000/predict`
- Duration: 14,400 s of 14,400 s configured (full duration completed)
- Window: 2026-10-20T21:26:19.814113+00:00 → 2026-10-21T01:26:19.918388+00:00
- Load: 2 closed-loop workers (max in flight observed 2), rate limit none, timeout 30.0 s, warm-up 600.0 s

## Requests (steady state, warm-up excluded)

| Attempted | Successful | Failed | Timeouts | Connection errors | Error rate | Throughput (req/s) |
|---:|---:|---:|---:|---:|---:|---:|
| 30,401 | 30,400 | 1 | 0 | 1 | 0.0033% | 2.203 |

Status codes: {'200': 30400}

## Latency of successful requests (ms, client-observed)

| Mean | p50 | p90 | p95 | p99 | Max |
|---:|---:|---:|---:|---:|---:|
| 907.6 | 794.7 | 1,497.6 | 1,789.7 | 2,408.7 | 22,863.3 |

Method: fixed log-bucket histogram, relative error <= 1.0%

## Service memory (RSS)

- Startup sample: 387.9 MB
- Baseline (median [600.0, 2400.0] s, 180 samples): 450.7 MB
- End window (median [12600.003635699977, 14400.003635699977] s, 179 samples): 362.9 MB
- Drift: -87.8 MB = -19.481% (gate: strict < 5.0%) → **PASS**
- Peak: 494.7 MB at 1194.345 s (peak − baseline 44.1 MB)

Trend: leak suspected = **False**; Theil–Sen -24.2 MB/h; projected 24 h growth -128.79634488547563% of baseline; rising window steps 2/5; RSS↔requests Pearson -0.7473618233545973. Trend analysis on a single run cannot prove absence of a leak; it flags sustained growth only

## Service memory (private committed bytes, Windows)

RSS on Windows is the working set, which the OS can trim; private bytes are the better leak signal.

- Baseline 593.8 MB → end 600.3 MB: 1.102% → **PASS**
- Peak 608.8 MB at 6660.013 s
- Trend: leak suspected = **True**; Theil–Sen 1.5 MB/h; projected 24 h 6.119063841128149% of baseline; rising steps 5/5; window medians [595.0, 595.6, 595.9, 598.3, 599.6, 599.8] MB

## Other resources

- handles: {'baseline_median': 472.0, 'end_median': 474, 'max': 485, 'growth': 2.0}
- threads: {'baseline_median': 8.0, 'end_median': 8, 'max': 15, 'growth': 0.0}
- children: {'baseline_median': 0.0, 'end_median': 0, 'max': 0, 'growth': 0.0}
- process_cpu_percent: {'mean': 248.59302325581396, 'max': 270.2, 'note': 'psutil per-process CPU; 100% = one logical core'}
- system_cpu_percent: {'mean': 88.48516713091922, 'max': 100.0}
- harness_rss_bytes: {'first': 49172480, 'last': 52006912, 'max': 53682176}

## Gates

| Gate | Status | Detail |
|---|---|---|
| run_completed | PASS | {'reason': '14400s of 14400s'} |
| service_restarts | PASS | {'restarts': 0} |
| telemetry_continuity | PASS | {'gaps': 0, 'sampling_failures': 0} |
| handle_or_fd_growth | UNDEFINED_THRESHOLD | {'measured_growth': 2.0, 'reason': 'no approved limit'} |
| thread_growth | UNDEFINED_THRESHOLD | {'measured_growth': 0.0, 'reason': 'no approved limit'} |
| error_rate | UNDEFINED_THRESHOLD | {'measured': 3.2893654813986384e-05, 'reason': 'no approved error-rate SLA'} |
| p95_latency | UNDEFINED_THRESHOLD | {'measured_ms': 1789.719360978148, 'reason': 'no approved latency SLA'} |
| memory_drift | PASS | {'threshold_percent': 5.0, 'comparison': 'strict <', 'reason': 'drift -19.481% vs < 5.0%'} |
| memory_ceiling | UNDEFINED_THRESHOLD | {'threshold_bytes': None, 'reason': 'no approved absolute memory ceiling'} |
| memory_trend | PASS | {'reason': 'no sustained growth by the declared criteria'} |
| memory_drift_private_bytes | PASS | {'threshold_percent': 5.0, 'comparison': 'strict <', 'reason': 'drift 1.102% vs < 5.0%'} |
| memory_trend_private_bytes | FAIL | {'reason': 'sustained growth by the declared criteria: Theil-Sen 1.51 MB/h, projected 6.119063841128149% of baseline per 24 h, 5/5 rising window steps'} |

## Profiler

1436 samples every 10.0 s; sampling failures 0; gaps 0; restarts 0; unavailable metrics: {'fds': 'Windows: open handles recorded instead of file descriptors', 'python_gc_tracemalloc': 'Service runs in a separate process; Python GC/allocation stats are not observable externally', 'gpu': 'CPU deployment; no GPU in use', 'container': 'Service not run in a container for this run'}

## Limitations

- No approved latency/error-rate SLA: those gates report measurements as UNDEFINED_THRESHOLD
- Client-observed latency includes HTTP/multipart overhead on loopback
- Service Python GC/allocation stats are not observable from a separate process
- Memory trend analysis on one run flags sustained growth; it cannot prove absence of a leak
- Physical network disconnection not exercised; offline means loopback-only target
