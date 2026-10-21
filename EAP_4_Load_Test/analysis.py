"""Memory-drift gate, leak-trend analysis and acceptance evaluation for EAP-4.

Gate (task requirement): drift_percent = (end - baseline) / baseline * 100 must be
strictly < max_memory_drift_percent, where baseline = median service RSS over
[warmup, warmup + baseline_window) and end = median RSS over the final end_window
of the actual run. Trend analysis is reported separately: a drift under 5% is not
evidence that no leak exists.
"""
from __future__ import annotations

import json
import math
import statistics
from pathlib import Path
from typing import Iterable, Optional

from .config import LoadTestConfig

GATE_STATUSES = ("PASS", "FAIL", "NOT_VERIFIED", "UNDEFINED_THRESHOLD")


def read_samples(path: Path) -> tuple[list[dict], int]:
    """Read JSONL samples; a truncated final line (interrupted write) is skipped and counted."""
    rows, bad = [], 0
    if not Path(path).is_file():
        return rows, bad
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            bad += 1
    return rows, bad


def _valid(rows: Iterable[dict], key: str) -> list[tuple[float, float]]:
    out = []
    for r in rows:
        v = r.get(key)
        if isinstance(v, (int, float)) and math.isfinite(v) and v > 0 and r.get("process_alive", True):
            out.append((float(r["elapsed_s"]), float(v)))
    return out


def theil_sen(points: list[tuple[float, float]], max_points: int = 400) -> Optional[float]:
    if len(points) < 3:
        return None
    step = max(1, len(points) // max_points)
    pts = points[::step]
    slopes = [(y2 - y1) / (x2 - x1) for i, (x1, y1) in enumerate(pts) for x2, y2 in pts[i + 1:] if x2 != x1]
    return statistics.median(slopes) if slopes else None


def ols_slope(points: list[tuple[float, float]]) -> Optional[float]:
    if len(points) < 3:
        return None
    xs, ys = zip(*points)
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    den = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in points) / den if den else None


def pearson(xs: list[float], ys: list[float]) -> Optional[float]:
    if len(xs) < 3:
        return None
    try:
        return statistics.correlation(xs, ys)
    except statistics.StatisticsError:
        return None


def memory_analysis(rows: list[dict], cfg: LoadTestConfig, actual_duration: float, completed: bool,
                    key: str = "rss_bytes") -> dict:
    t = cfg.thresholds
    pts = _valid(rows, key)
    out = dict(measurement=f"service process {key.replace('_bytes', '')} (psutil memory_info)", unit="bytes",
               valid_samples=len(pts), startup_bytes=pts[0][1] if pts else None,
               startup_note="first sample after the harness attached (service already started)")
    base_lo, base_hi = cfg.warmup_seconds, cfg.warmup_seconds + cfg.baseline_window_seconds
    end_lo = actual_duration - cfg.end_window_seconds
    base = [v for x, v in pts if base_lo <= x < base_hi]
    end = [v for x, v in pts if x >= end_lo and x >= base_hi]
    out.update(baseline_window_s=[base_lo, base_hi], end_window_s=[max(end_lo, base_hi), actual_duration],
               baseline_samples=len(base), end_window_samples=len(end), aggregation="median")
    gate = dict(name="memory_drift", threshold_percent=t.max_memory_drift_percent, comparison="strict <")
    if len(base) < cfg.min_samples_per_window or len(end) < cfg.min_samples_per_window:
        gate.update(status="NOT_VERIFIED", reason=f"insufficient samples (baseline {len(base)}, end {len(end)}, "
                                                  f"need >= {cfg.min_samples_per_window} each)")
    else:
        b, e = statistics.median(base), statistics.median(end)
        drift = (e - b) / b * 100
        out.update(baseline_bytes=b, end_window_bytes=e, absolute_drift_bytes=e - b, drift_percent=drift)
        passed = drift < t.max_memory_drift_percent
        if not completed:
            gate.update(status="NOT_VERIFIED", reason=f"run interrupted at {actual_duration:.0f}s of "
                        f"{cfg.duration_seconds:.0f}s; drift {drift:.3f}% covers the partial run only")
        else:
            gate.update(status="PASS" if passed else "FAIL", reason=f"drift {drift:.3f}% vs < {t.max_memory_drift_percent}%")
    out["drift_gate"] = gate
    if pts:
        peak_x, peak_v = max(pts, key=lambda p: p[1])
        out.update(peak_bytes=peak_v, peak_elapsed_s=peak_x,
                   peak_minus_baseline_bytes=peak_v - out["baseline_bytes"] if "baseline_bytes" in out else None)
    ceiling = dict(name="memory_ceiling", threshold_bytes=t.memory_ceiling_bytes)
    if t.memory_ceiling_bytes is None:
        ceiling.update(status="UNDEFINED_THRESHOLD", reason="no approved absolute memory ceiling")
    elif not pts:
        ceiling.update(status="NOT_VERIFIED", reason="no valid samples")
    else:
        over = [x for x, v in pts if v >= t.memory_ceiling_bytes]
        ceiling.update(status="FAIL" if over else "PASS", first_exceeded_s=over[0] if over else None)
    out["ceiling_gate"] = ceiling
    out["trend"] = trend_analysis(rows, pts, cfg, out.get("baseline_bytes"))
    return out


def trend_analysis(rows: list[dict], pts: list[tuple[float, float]], cfg: LoadTestConfig,
                   baseline: Optional[float], windows: int = 6) -> dict:
    steady = [(x, v) for x, v in pts if x >= cfg.warmup_seconds]
    if len(steady) < max(12, windows * 2):
        return dict(evidence_sufficient=False, leak_suspected=None,
                    reason=f"{len(steady)} post-warm-up samples is too few for trend analysis")
    hours = [(x / 3600, v) for x, v in steady]
    ts, ols = theil_sen(hours), ols_slope(hours)
    span = steady[-1][0] - steady[0][0]
    medians = []
    for i in range(windows):
        lo = steady[0][0] + span * i / windows
        hi = steady[0][0] + span * (i + 1) / windows
        vals = [v for x, v in steady if lo <= x < hi or (i == windows - 1 and x == hi)]
        if vals:
            medians.append(dict(window=i + 1, start_s=lo, end_s=hi, median_bytes=statistics.median(vals), samples=len(vals)))
    rises = sum(1 for a, b in zip(medians, medians[1:]) if b["median_bytes"] > a["median_bytes"])
    ref = baseline or steady[0][1]
    peak_x, peak_v = max(steady, key=lambda p: p[1])
    post_peak = [v for x, v in steady if x > peak_x]
    req_pairs = [(r["requests_completed"], r["rss_bytes"]) for r in rows
                 if r.get("requests_completed") is not None and isinstance(r.get("rss_bytes"), (int, float))
                 and r["elapsed_s"] >= cfg.warmup_seconds]
    corr = pearson([a for a, _ in req_pairs], [b for _, b in req_pairs]) if req_pairs else None
    per_req = None
    if len(req_pairs) >= 3 and req_pairs[-1][0] > req_pairs[0][0]:
        slope = ols_slope([(float(a), float(b)) for a, b in req_pairs])
        per_req = slope * 1000 if slope is not None else None
    # Declared before measurement: a leak is suspected only if growth is sustained
    # (every window-to-window step rises) AND material (> 1% of baseline across the
    # steady state), or if the robust slope would add >= 5% of baseline per 24 h.
    total_growth = medians[-1]["median_bytes"] - medians[0]["median_bytes"] if len(medians) > 1 else 0.0
    sustained = len(medians) >= 4 and rises == len(medians) - 1 and total_growth > 0.01 * ref
    projected_24h_pct = ts * 24 / ref * 100 if ts is not None and ref else None
    fast = projected_24h_pct is not None and projected_24h_pct >= 5
    return dict(evidence_sufficient=True, leak_suspected=bool(sustained or fast),
                method="Theil-Sen + OLS slope over post-warm-up RSS; 6 equal rolling windows (medians)",
                theil_sen_slope_bytes_per_hour=ts, ols_slope_bytes_per_hour=ols,
                projected_24h_growth_percent_of_baseline=projected_24h_pct,
                window_medians=medians, rising_window_steps=rises, window_steps=max(0, len(medians) - 1),
                steady_state_growth_bytes=total_growth,
                peak_elapsed_s=peak_x, peak_bytes=peak_v,
                post_peak_min_bytes=min(post_peak) if post_peak else None,
                rss_vs_completed_requests_pearson=corr, rss_growth_bytes_per_1000_requests=per_req,
                criteria="leak_suspected if all window steps rise and growth > 1% of baseline, "
                         "or Theil-Sen slope projects >= 5% of baseline per 24 h",
                caveat="Trend analysis on a single run cannot prove absence of a leak; it flags sustained growth only")


def private_bytes_gates(rows: list[dict], cfg: LoadTestConfig, actual_duration: float, completed: bool,
                        windows_platform: bool) -> tuple[Optional[dict], list[dict]]:
    """On Windows psutil RSS is the *working set*, which the OS may trim; psutil `vms` is private
    committed bytes, the better leak signal. Apply the same drift gate and trend criteria to it."""
    if not windows_platform:
        return None, []
    memory = memory_analysis(rows, cfg, actual_duration, completed, key="vms_bytes")
    memory["measurement"] = "service process private committed bytes (psutil vms on Windows)"
    drift = dict(memory["drift_gate"], name="memory_drift_private_bytes")
    trend = memory["trend"]
    trend_gate = dict(name="memory_trend_private_bytes",
                      status="FAIL" if trend.get("leak_suspected") else
                      ("PASS" if trend.get("evidence_sufficient") and completed else "NOT_VERIFIED"),
                      reason=("sustained growth by the declared criteria: Theil-Sen "
                              f"{(trend.get('theil_sen_slope_bytes_per_hour') or 0) / 1e6:.2f} MB/h, projected "
                              f"{trend.get('projected_24h_growth_percent_of_baseline')}% of baseline per 24 h, "
                              f"{trend.get('rising_window_steps')}/{trend.get('window_steps')} rising window steps")
                      if trend.get("leak_suspected") else (trend.get("reason") or "no sustained growth by the declared criteria"))
    return memory, [drift, trend_gate]


def resource_growth(rows: list[dict], cfg: LoadTestConfig, actual_duration: float) -> dict:
    out = {}
    base_hi = cfg.warmup_seconds + cfg.baseline_window_seconds
    for key in ("handles", "fds", "threads", "children"):
        vals = [(r["elapsed_s"], r[key]) for r in rows if isinstance(r.get(key), (int, float))]
        if not vals:
            continue
        base = [v for x, v in vals if cfg.warmup_seconds <= x < base_hi]
        end = [v for x, v in vals if x >= actual_duration - cfg.end_window_seconds and x >= base_hi]
        out[key] = dict(baseline_median=statistics.median(base) if base else None,
                        end_median=statistics.median(end) if end else None,
                        max=max(v for _, v in vals),
                        growth=(statistics.median(end) - statistics.median(base)) if base and end else None)
    cpu = [r["process_cpu_percent"] for r in rows if isinstance(r.get("process_cpu_percent"), (int, float))
           and r["elapsed_s"] >= cfg.warmup_seconds]
    if cpu:
        out["process_cpu_percent"] = dict(mean=statistics.fmean(cpu), max=max(cpu),
                                          note="psutil per-process CPU; 100% = one logical core")
    sys_cpu = [r["system_cpu_percent"] for r in rows if isinstance(r.get("system_cpu_percent"), (int, float))]
    if sys_cpu:
        out["system_cpu_percent"] = dict(mean=statistics.fmean(sys_cpu), max=max(sys_cpu))
    harness = [r["harness_rss_bytes"] for r in rows if isinstance(r.get("harness_rss_bytes"), (int, float))]
    if harness:
        out["harness_rss_bytes"] = dict(first=harness[0], last=harness[-1], max=max(harness))
    return out


def count_gate(name: str, growth: Optional[float], limit: Optional[int]) -> dict:
    if limit is None:
        return dict(name=name, status="UNDEFINED_THRESHOLD", measured_growth=growth, reason="no approved limit")
    if growth is None:
        return dict(name=name, status="NOT_VERIFIED", reason="metric unavailable or insufficient samples")
    return dict(name=name, status="PASS" if growth <= limit else "FAIL", measured_growth=growth, threshold=limit)


def request_gates(steady: dict, cfg: LoadTestConfig) -> list[dict]:
    t = cfg.thresholds
    gates = []
    err = steady.get("error_rate")
    if t.max_error_rate is None:
        gates.append(dict(name="error_rate", status="UNDEFINED_THRESHOLD", measured=err, reason="no approved error-rate SLA"))
    elif err is None:
        gates.append(dict(name="error_rate", status="NOT_VERIFIED", reason="no steady-state requests"))
    else:
        gates.append(dict(name="error_rate", status="PASS" if err <= t.max_error_rate else "FAIL", measured=err,
                          threshold=t.max_error_rate))
    p95 = steady.get("latency_success", {}).get("p95_ms")
    if t.max_p95_latency_ms is None:
        gates.append(dict(name="p95_latency", status="UNDEFINED_THRESHOLD", measured_ms=p95, reason="no approved latency SLA"))
    elif p95 is None:
        gates.append(dict(name="p95_latency", status="NOT_VERIFIED", reason="no successful steady-state requests"))
    else:
        gates.append(dict(name="p95_latency", status="PASS" if p95 <= t.max_p95_latency_ms else "FAIL",
                          measured_ms=p95, threshold_ms=t.max_p95_latency_ms))
    return gates


def overall_status(completed: bool, gates: list[dict]) -> str:
    """INTERRUPTED dominates; then FAIL; PASS only if every gate PASSed (undefined thresholds are not passes)."""
    if not completed:
        return "INTERRUPTED"
    statuses = {g["status"] for g in gates}
    if "FAIL" in statuses:
        return "FAIL"
    if statuses <= {"PASS"}:
        return "PASS"
    return "NOT_VERIFIED"
