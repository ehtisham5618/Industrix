# ESE-CPU3 one-hour CPU soak

Task-specific tools live in this separate folder. The required entry point is
`SED_3_Stress_Testing/scripts/soak_test.py`; it reuses CPU2's existing capture
workers, fixed raw rings and deterministic sampler rather than creating another
three-stream ingestion pipeline.

```powershell
& ESE_CPU1_Quantization/runtime/venv/Scripts/python.exe SED_3_Stress_Testing/scripts/soak_test.py --duration 3600 --engine openvino --streams 3
```

The default warmup is 60 seconds **before** the 3600-second measured period, in
the same process without restarting ingestion. Source-video rewinds reset only
the relevant tracking/escalation session. A temporary Windows system-awake
request is cleared during shutdown; the system power plan is not edited. A
telemetry gap greater than 15 seconds invalidates continuity.

The actual CPU1-selected OpenVINO INT8 XML/BIN/metadata hashes are verified before
CPU compilation. No PyTorch fallback, retraining, export rerun or alternate model
is permitted. Input batch1/640x640, LATENCY hint, one OpenVINO stream, two threads
are the CPU1 settings. Shared micro-batches are evaluated sequentially with the
static batch1 engine. Real NMS, coordinate rescaling, calibrated ByteTRACK,
15 evaluated-observation confirmation and software-only SED-2 escalation remain.
CPU1's prior failed accuracy/size/latency targets are preserved, not overwritten.

Three CPU2 local simulations retain their native resolutions/FPS and loop:
factory documentary (25 FPS), hazmat exercise (29.946 FPS), rooftop workers
(23.976 FPS). Camera names represent intended deployment roles. Actual RTSP
protocol validation is not claimed. Their 1-in-4 sampling ceiling is 19.7305 FPS
aggregate, which conflicts with the task's operational >=45 FPS target.
`capacity.py` separately measures ready-tensor engine capacity and CPU settings;
capacity is never reported as actual camera-processing throughput.

The real host is an Intel i5-7200U, two physical/four logical cores, about 16 GiB
RAM, Windows 11. Full report records exact versions and measurements. Supported
psutil CPU-frequency telemetry is sampled; Windows reported MHz may be nominal.
This host exposes no supported CPU temperature or explicit throttling counter.
Missing thermal data remains null/blank and cannot establish a no-throttling claim.

Memory uses **both** process RSS and tracemalloc. Full telemetry/latencies stream
to CSV rather than accumulating in RAM; existing fixed diagnostic histories
remain bounded. Optional SED-2 retention in this harness limits histories and
resolved archives to 1024 records, archives to JSONL, and never evicts live safety
incidents. Default API/event-store behavior remains compatible.

The declared memory heuristic excludes warmup, fits overall/late trends and
compares stable early/final windows. Sustained-growth evidence requires all
three indicators, with minimum material RSS/Python growth 10/1 MiB and relative
threshold 5% of early memory, slope threshold at least 2%/hour. Bounded cache
fill that plateaus is allowed. Native/capture thread counts, ring occupancy,
reconnects and exceptions are checked separately. No claim of mathematical leak
freedom is made from tracemalloc alone.

Outputs:

- `SED_3_Stress_Testing/reports/cpu_soak_report.json`
- `cpu_soak_timeseries.csv`, `cpu_soak_inference.csv`, `cpu_soak_frames.csv`
- `cpu_soak_allocation_deltas.json`
- `cpu_soak_cpu.png`, `cpu_soak_memory.png`, `cpu_soak_fps.png`, `cpu_soak_thermal.png`
- `ESE_CPU3_Soak_Test_Report.md`
- CPU3 test/capacity/delivery evidence in `ESE_CPU3_Soak_Test/reports/`

Run duration can be shorter for development; it can never satisfy the one-hour
gate. `status=completed` describes completion of the requested run; DoD and
`overall` separately evaluate the actual hour and measured target. Exit code 2
means completed reporting with failed acceptance, not an unhandled crash.

## Offline commits and recovery

Exactly two new CPU3 task commits are saved on
`feature/atlantis-cpu-soak-test`, based on completed CPU2 HEAD. Both are made only
after actual one-hour evidence exists. No push/PR while access is revoked.
When organization permission returns, from the original repository:

```powershell
git push -u origin feature/atlantis-cpu-soak-test
```

Or run `ESE_CPU3_Soak_Test/sync_when_access_returns.ps1`. Normal push preserves
the saved commit IDs; upstream is established only after the remote branch exists.
`offline_backup.py` verifies a complete Git bundle by actually cloning it, and
verifies every runtime ZIP file by SHA256. The ZIP contains the source/INT8 models,
three videos, local MLflow state and small alert archive; no Python environment.

To restore elsewhere, clone the bundle branch, extract the runtime ZIP into the
clone, install requirements into a CPU Python environment, then set origin:

```powershell
git -C <restored-folder> remote set-url origin https://github.com/devlogixtechnology/industirx.git
git -C <restored-folder> push -u origin feature/atlantis-cpu-soak-test
```
