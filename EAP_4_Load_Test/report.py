"""Human-readable Markdown report generated from an EAP-4 summary dict."""
from __future__ import annotations

from pathlib import Path


def _mb(value) -> str:
    return "n/a" if value is None else f"{value / 1e6:,.1f} MB"


def _ms(value) -> str:
    return "n/a" if value is None else f"{value:,.1f}"


def _private_lines(pb) -> list:
    if not pb:
        return []
    tr = pb.get("trend", {})
    drift = "n/a" if pb.get("drift_percent") is None else f"{pb['drift_percent']:.3f}%"
    medians = [round(w["median_bytes"] / 1e6, 1) for w in tr.get("window_medians", [])]
    return ["## Service memory (private committed bytes, Windows)", "",
            "RSS on Windows is the working set, which the OS can trim; private bytes are the better leak signal.", "",
            f"- Baseline {_mb(pb.get('baseline_bytes'))} → end {_mb(pb.get('end_window_bytes'))}: {drift} → "
            f"**{pb['drift_gate']['status']}**",
            f"- Peak {_mb(pb.get('peak_bytes'))} at {pb.get('peak_elapsed_s')} s",
            f"- Trend: leak suspected = **{tr.get('leak_suspected')}**; Theil–Sen {_mb(tr.get('theil_sen_slope_bytes_per_hour'))}/h; "
            f"projected 24 h {tr.get('projected_24h_growth_percent_of_baseline')}% of baseline; rising steps "
            f"{tr.get('rising_window_steps')}/{tr.get('window_steps')}; window medians {medians} MB", ""]


def write_markdown(s: dict, path: Path) -> None:
    req = s["request_metrics"]["steady_state"]
    lat = req.get("latency_success", {})
    mem = s["memory_metrics"]
    trend = mem.get("trend", {})
    res = s.get("resource_metrics", {})
    error_rate = "n/a" if req["error_rate"] is None else f"{req['error_rate']:.4%}"
    throughput = "n/a" if req["throughput_rps"] is None else f"{req['throughput_rps']:.3f}"
    lines = [f"# EAP-4 load test — {s['run_id']}", "",
             f"**Status: {s['status']}** · run state {s['run_state']} · profile `{s['profile']}`", "",
             f"- Target: `{s['target']}`",
             f"- Duration: {s['actual_duration_seconds']:,.0f} s of {s['configured_duration_seconds']:,.0f} s configured "
             f"({'full duration completed' if s['full_duration_completed'] else 'NOT completed'})",
             f"- Window: {s['started_at']} → {s['ended_at']}",
             f"- Load: {s['effective_config']['concurrency']} closed-loop workers (max in flight observed "
             f"{s.get('max_in_flight_observed')}), rate limit {s['effective_config']['requests_per_second'] or 'none'}, "
             f"timeout {s['effective_config']['request_timeout_seconds']} s, warm-up {s['effective_config']['warmup_seconds']} s", "",
             "## Requests (steady state, warm-up excluded)", "",
             "| Attempted | Successful | Failed | Timeouts | Connection errors | Error rate | Throughput (req/s) |",
             "|---:|---:|---:|---:|---:|---:|---:|",
             f"| {req['attempted']:,} | {req['successful']:,} | {req['failed']:,} | {req['timeouts']:,} | "
             f"{req['connection_errors']:,} | {error_rate} | {throughput} |",
             "", f"Status codes: {req['status_codes']}", "",
             "## Latency of successful requests (ms, client-observed)", "",
             "| Mean | p50 | p90 | p95 | p99 | Max |", "|---:|---:|---:|---:|---:|---:|",
             f"| {_ms(lat.get('mean_ms'))} | {_ms(lat.get('p50_ms'))} | {_ms(lat.get('p90_ms'))} | {_ms(lat.get('p95_ms'))} | "
             f"{_ms(lat.get('p99_ms'))} | {_ms(lat.get('max_ms'))} |", "", f"Method: {lat.get('method', 'n/a')}", "",
             "## Service memory (RSS)", "",
             f"- Startup sample: {_mb(mem.get('startup_bytes'))}",
             f"- Baseline (median {mem.get('baseline_window_s')} s, {mem.get('baseline_samples')} samples): {_mb(mem.get('baseline_bytes'))}",
             f"- End window (median {mem.get('end_window_s')} s, {mem.get('end_window_samples')} samples): {_mb(mem.get('end_window_bytes'))}",
             f"- Drift: {_mb(mem.get('absolute_drift_bytes'))} = "
             f"{'n/a' if mem.get('drift_percent') is None else format(mem['drift_percent'], '.3f') + '%'} "
             f"(gate: strict < {mem['drift_gate']['threshold_percent']}%) → **{mem['drift_gate']['status']}**",
             f"- Peak: {_mb(mem.get('peak_bytes'))} at {mem.get('peak_elapsed_s')} s "
             f"(peak − baseline {_mb(mem.get('peak_minus_baseline_bytes'))})", "",
             f"Trend: leak suspected = **{trend.get('leak_suspected')}**; Theil–Sen "
             f"{_mb(trend.get('theil_sen_slope_bytes_per_hour'))}/h; projected 24 h growth "
             f"{trend.get('projected_24h_growth_percent_of_baseline')}% of baseline; rising window steps "
             f"{trend.get('rising_window_steps')}/{trend.get('window_steps')}; RSS↔requests Pearson "
             f"{trend.get('rss_vs_completed_requests_pearson')}. {trend.get('caveat', trend.get('reason', ''))}", "",
             *_private_lines(s.get("private_bytes_metrics")),
             "## Other resources", ""]
    for key, value in res.items():
        lines.append(f"- {key}: {value}")
    lines += ["", "## Gates", "", "| Gate | Status | Detail |", "|---|---|---|"]
    for gate in s["checks"]:
        detail = {k: v for k, v in gate.items() if k not in ("name", "status")}
        lines.append(f"| {gate['name']} | {gate['status']} | {detail} |")
    prof = s["profiler"]
    lines += ["", "## Profiler", "",
              f"{prof['samples']} samples every {prof['interval_seconds']} s; sampling failures {prof['sampling_failures']}; "
              f"gaps {len(prof['gaps'])}; restarts {len(prof['restarts'])}; unavailable metrics: {prof['unavailable']}", "",
              "## Limitations", "", *[f"- {item}" for item in s["limitations"]]]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
