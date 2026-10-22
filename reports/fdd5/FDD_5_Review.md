# FDD-5 — Official Dry Run Rehearsal for Demo Day: Review

**Status: IMPLEMENTED — REVIEW BLOCKED.** An automated end-to-end dry run of the real product ran on
2026-10-22 and finished READY, with 59 of 59 checks PASS. It is blocked only by items outside the run:
GitHub Actions has never run on this repo, physical network isolation is untested, and no human presenter
walk-through has been done on the Demo Day laptop.

## What was rehearsed (final run)
Report: `reports/fdd5/rehearsal/rehearsal_20261022T182610Z.json` · log: `reports/fdd5/rehearsal_terminal.txt`

| Item | Value |
|---|---|
| Run window | 18:26:10–18:28:34 UTC (23:26–23:28 PKT), about 2.4 minutes |
| Revision | 689d30b plus the FDD-5 working tree, committed unchanged as 5b55d7d |
| Machine | Windows 11, Intel 4 logical CPUs, Python 3.12.9 (ESE_CPU1 venv) |

| Stage | Result |
|---|---|
| A readiness | 29/29 PASS: imports, `best.pt` SHA256, configs, ports, writable dirs, disk 6.3 GB free, Playwright and Edge, samples, ffmpeg |
| B startup | watchdog start, both services healthy after 22.2 s, FDD-3 smoke test 6/6 |
| C workflow | dashboard opened. Textile sample gives **baekra 95.0%** (2.69 s click-to-results). Fire sample gives **fire 81.7%, smoke 40.0%, smoke 32.5%** (1.03 s). In both cases the dashboard table matched a direct `/predict` on the same file exactly. Incident History rendered (0 hazard and 0 quality incidents in the local store, 0 logging failures). |
| D recovery | dashboard pointed at a dead backend shows "FastAPI backend is unavailable" and a reload recovers it; corrupt PNG and text file return 400; empty multipart returns 422; 1 ms client timeout is reported and the backend stays healthy; missing model is detected; watchdog refuses to start a config with a missing model (exit 1) or with no `services` (exit 2); recorder refuses without ffmpeg; probe of a dead port is reported |
| D11 crash | watchdog-owned backend process tree killed; watchdog restarted it, healthy after 12.0 s, `/predict` gave 3 detections |
| D12 restart | graceful stop freed the ports (18.4 s); restart healthy after 20.2 s; smoke 6/6; final stop 3.8 s |

Timings are single-run observations on this laptop, not benchmarks. No latency SLA exists.

## Resources (observations, no threshold)
psutil sampled every 2 s, 52 samples over 106.7 s.
- Backend process-tree RSS: 31.8 MiB at first sample (still loading), maximum 460.0 MiB, 421.1 MiB at the last sample. The series includes a deliberate crash and restart.
- System CPU: mean 58.3%, maximum 100%.
- **Memory drift < 5% is NOT VERIFIED.** A rehearsal of minutes that includes a restart cannot measure drift. EAP-4 is the long-run profile, and it reported private-bytes growth.

## Offline (level achieved)
- 0 non-loopback browser requests (guard active).
- 0 non-loopback sockets on the backend process tree in any sample.
- The backend is started with `YOLO_OFFLINE=true` and `YOLO_AUTOINSTALL=false`, and the model is a local file verified by checksum.
- **Physical network isolation was not performed.**

## Runs
1. `rehearsal_run1_superseded_20261022T182146Z.json` / `rehearsal_terminal_run1.txt`: also READY, but its memory figures are wrong. The watchdog-owned PID on Windows is the venv launcher (about 5 MiB); the interpreter is its child. The incident-count detail also printed "?". Both were fixed: RSS and sockets are now summed over the process tree, and the incident counts are read from the `/incidents` object. `read_status` was also changed so tests can redirect the status path. The rehearsal was then rerun.
2. `rehearsal_20261022T182610Z.json`: final.

## Validation
- `pytest FDD_5_Dry_Run/tests -v -rs`: **21 passed**. Covers readiness classification (a skipped required check is never a pass), report schema round-trip, path redaction, no-overwrite, results-table parsing and comparison, readiness waits and timeouts, status-file errors, a real local HTTP probe and a dead port, refusal on busy ports, services stopped on Ctrl+C, a preflight failure starting nothing, the offline guard and no cloud clients, killing only the watchdog-owned process, doc/command consistency, and consistency of the committed report.
- flake8 (max-line 160) and the CI subset (E9, F63, F7, F82) are clean.
- Full repository suite (`repository_pytest_output.txt`): **683 passed, 2 failed, 12 skipped**. Both failures are the pre-existing ESE-CPU1 INT8 gates (IR size 11,773,383 B vs 6.5 MB; mAP drop vs 1.0 pp); 683 = 661 FDD-4 baseline + 1 FDD-4 test + 21 FDD-5 tests.

## Not verified / risks
- Physical offline.
- Memory drift.
- A human walk-through on the Demo Day laptop and projector.
- GitHub Actions.
- Live three-camera streaming, `/docs` and PDF export are deliberately excluded from the demo.
- System CPU reached 100% during the run, so close other applications before presenting.
- Carried over: EAP-4 memory growth and the ESE-CPU1 INT8 gate failures.
