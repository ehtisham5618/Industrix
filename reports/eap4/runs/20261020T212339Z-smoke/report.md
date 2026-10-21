# EAP-4 load test — 20261020T212339Z-smoke

**Status: NOT_VERIFIED** · run state COMPLETED · profile `smoke`

- Target: `http://127.0.0.1:8000/predict`
- Duration: 61 s of 60 s configured (full duration completed)
- Window: 2026-10-20T21:23:40.117303+00:00 → 2026-10-20T21:24:41.041997+00:00
- Load: 2 closed-loop workers (max in flight observed 2), rate limit none, timeout 30.0 s, warm-up 10.0 s

## Requests (steady state, warm-up excluded)

| Attempted | Successful | Failed | Timeouts | Connection errors | Error rate | Throughput (req/s) |
|---:|---:|---:|---:|---:|---:|---:|
| 29 | 29 | 0 | 0 | 0 | 0.0000% | 0.568 |

Status codes: {'200': 29}

## Latency of successful requests (ms, client-observed)

| Mean | p50 | p90 | p95 | p99 | Max |
|---:|---:|---:|---:|---:|---:|
| 3,306.2 | 2,225.3 | 8,725.7 | 10,849.3 | n/a | 11,172.0 |

Method: fixed log-bucket histogram, relative error <= 1.0%

## Service memory (RSS)

- Startup sample: 387.1 MB
- Baseline (median [10.0, 25.0] s, 7 samples): 442.9 MB
- End window (median [46.018180900020525, 61.018180900020525] s, 7 samples): 439.6 MB
- Drift: -3.2 MB = -0.725% (gate: strict < 5.0%) → **PASS**
- Peak: 461.6 MB at 10.715 s (peak − baseline 18.7 MB)

Trend: leak suspected = **False**; Theil–Sen -332.3 MB/h; projected 24 h growth -1800.6275907998045% of baseline; rising window steps 3/5; RSS↔requests Pearson -0.14729269008055146. Trend analysis on a single run cannot prove absence of a leak; it flags sustained growth only

## Other resources

- handles: {'baseline_median': 483, 'end_median': 476, 'max': 485, 'growth': -7}
- threads: {'baseline_median': 12, 'end_median': 11, 'max': 14, 'growth': -1}
- children: {'baseline_median': 0, 'end_median': 0, 'max': 0, 'growth': 0}
- process_cpu_percent: {'mean': 69.46666666666667, 'max': 132.1, 'note': 'psutil per-process CPU; 100% = one logical core'}
- system_cpu_percent: {'mean': 96.53793103448275, 'max': 100.0}
- harness_rss_bytes: {'first': 49692672, 'last': 50880512, 'max': 50941952}

## Gates

| Gate | Status | Detail |
|---|---|---|
| run_completed | PASS | {'reason': '61s of 60s'} |
| memory_drift | PASS | {'threshold_percent': 5.0, 'comparison': 'strict <', 'reason': 'drift -0.725% vs < 5.0%'} |
| memory_ceiling | UNDEFINED_THRESHOLD | {'threshold_bytes': None, 'reason': 'no approved absolute memory ceiling'} |
| service_restarts | PASS | {'restarts': 0} |
| telemetry_continuity | PASS | {'gaps': 0, 'sampling_failures': 0} |
| handle_or_fd_growth | UNDEFINED_THRESHOLD | {'measured_growth': -7, 'reason': 'no approved limit'} |
| thread_growth | UNDEFINED_THRESHOLD | {'measured_growth': -1, 'reason': 'no approved limit'} |
| error_rate | UNDEFINED_THRESHOLD | {'measured': 0.0, 'reason': 'no approved error-rate SLA'} |
| p95_latency | UNDEFINED_THRESHOLD | {'measured_ms': 10849.271229439855, 'reason': 'no approved latency SLA'} |
| memory_trend | PASS | {'reason': 'no sustained growth by the declared criteria'} |

## Profiler

29 samples every 2.0 s; sampling failures 0; gaps 0; restarts 0; unavailable metrics: {'fds': 'Windows: open handles recorded instead of file descriptors', 'python_gc_tracemalloc': 'Service runs in a separate process; Python GC/allocation stats are not observable externally', 'gpu': 'CPU deployment; no GPU in use', 'container': 'Service not run in a container for this run'}

## Limitations

- No approved latency/error-rate SLA: those gates report measurements as UNDEFINED_THRESHOLD
- Client-observed latency includes HTTP/multipart overhead on loopback
- Service Python GC/allocation stats are not observable from a separate process
- Memory trend analysis on one run flags sustained growth; it cannot prove absence of a leak
- Physical network disconnection not exercised; offline means loopback-only target
