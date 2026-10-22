# EAP-4 load test — 20261022T170630Z-smoke

**Status: FAIL** · run state COMPLETED · profile `smoke`

- Target: `http://127.0.0.1:8000/predict`
- Duration: 181 s of 180 s configured (full duration completed)
- Window: 2026-10-22T17:06:30.524344+00:00 → 2026-10-22T17:09:31.384634+00:00
- Load: 2 closed-loop workers (max in flight observed 2), rate limit none, timeout 30.0 s, warm-up 20.0 s

## Requests (steady state, warm-up excluded)

| Attempted | Successful | Failed | Timeouts | Connection errors | Error rate | Throughput (req/s) |
|---:|---:|---:|---:|---:|---:|---:|
| 321 | 321 | 0 | 0 | 0 | 0.0000% | 1.995 |

Status codes: {'200': 321}

## Latency of successful requests (ms, client-observed)

| Mean | p50 | p90 | p95 | p99 | Max |
|---:|---:|---:|---:|---:|---:|
| 995.6 | 860.2 | 1,720.2 | 2,096.9 | 2,822.2 | 3,882.9 |

Method: fixed log-bucket histogram, relative error <= 1.0%

## Service memory (RSS)

- Startup sample: 458.1 MB
- Baseline (median [20.0, 50.0] s, 15 samples): 460.8 MB
- End window (median [150.875, 180.875] s, 14 samples): 478.1 MB
- Drift: 17.3 MB = 3.745% (gate: strict < 5.0%) → **PASS**
- Peak: 500.1 MB at 107.734 s (peak − baseline 39.3 MB)

Trend: leak suspected = **True**; Theil–Sen 413.9 MB/h; projected 24 h growth 2155.710543880383% of baseline; rising window steps 3/5; RSS↔requests Pearson 0.3573213983794391. Trend analysis on a single run cannot prove absence of a leak; it flags sustained growth only

## Service memory (private committed bytes, Windows)

RSS on Windows is the working set, which the OS can trim; private bytes are the better leak signal.

- Baseline 550.6 MB → end 592.1 MB: 7.538% → **FAIL**
- Peak 602.0 MB at 144.359 s
- Trend: leak suspected = **True**; Theil–Sen 1,192.1 MB/h; projected 24 h 5196.143131949836% of baseline; rising steps 3/5; window medians [551.1, 562.8, 552.1, 595.6, 588.2, 592.1] MB

## Other resources

- handles: {'baseline_median': 464, 'end_median': 454.0, 'max': 469, 'growth': -10.0}
- threads: {'baseline_median': 15, 'end_median': 9.0, 'max': 15, 'growth': -6.0}
- children: {'baseline_median': 0, 'end_median': 0.0, 'max': 0, 'growth': 0.0}
- process_cpu_percent: {'mean': 221.00759493670884, 'max': 286.8, 'note': 'psutil per-process CPU; 100% = one logical core'}
- system_cpu_percent: {'mean': 92.23033707865169, 'max': 100.0}
- harness_rss_bytes: {'first': 48525312, 'last': 49991680, 'max': 49991680}

## Gates

| Gate | Status | Detail |
|---|---|---|
| run_completed | PASS | {'reason': '181s of 180s'} |
| memory_drift | PASS | {'threshold_percent': 5.0, 'comparison': 'strict <', 'reason': 'drift 3.745% vs < 5.0%'} |
| memory_ceiling | UNDEFINED_THRESHOLD | {'threshold_bytes': None, 'reason': 'no approved absolute memory ceiling'} |
| service_restarts | PASS | {'restarts': 0} |
| telemetry_continuity | PASS | {'gaps': 0, 'sampling_failures': 0} |
| handle_or_fd_growth | UNDEFINED_THRESHOLD | {'measured_growth': -10.0, 'reason': 'no approved limit'} |
| thread_growth | UNDEFINED_THRESHOLD | {'measured_growth': -6.0, 'reason': 'no approved limit'} |
| error_rate | UNDEFINED_THRESHOLD | {'measured': 0.0, 'reason': 'no approved error-rate SLA'} |
| p95_latency | UNDEFINED_THRESHOLD | {'measured_ms': 2096.9414786514276, 'reason': 'no approved latency SLA'} |
| memory_drift_private_bytes | FAIL | {'threshold_percent': 5.0, 'comparison': 'strict <', 'reason': 'drift 7.538% vs < 5.0%'} |
| memory_trend_private_bytes | FAIL | {'reason': 'sustained growth by the declared criteria: Theil-Sen 1192.07 MB/h, projected 5196.143131949836% of baseline per 24 h, 3/5 rising window steps'} |
| memory_trend | FAIL | {'reason': 'sustained growth detected (see trend)'} |

## Profiler

89 samples every 2.0 s; sampling failures 0; gaps 0; restarts 0; unavailable metrics: {'fds': 'Windows: open handles recorded instead of file descriptors', 'python_gc_tracemalloc': 'Service runs in a separate process; Python GC/allocation stats are not observable externally', 'gpu': 'CPU deployment; no GPU in use', 'container': 'Service not run in a container for this run'}

## Limitations

- No approved latency/error-rate SLA: those gates report measurements as UNDEFINED_THRESHOLD
- Client-observed latency includes HTTP/multipart overhead on loopback
- Service Python GC/allocation stats are not observable from a separate process
- Memory trend analysis on one run flags sustained growth; it cannot prove absence of a leak
- Physical network disconnection not exercised; offline means loopback-only target
