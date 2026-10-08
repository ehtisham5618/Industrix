# ESE-CPU2 async ingestion

Task tools live in this separate folder; production ingestion remains in the
existing SED-1 stream manager. Each independent OpenCV capture worker writes all
raw frames into its own fixed 15-slot ring. Zero-based raw sequence modulo four
selects phase zero; only selected observations reach the shared detector,
CME-OPT3 ByteTRACK and unchanged 15-observation confirmation and SED-2 escalation.
This is frame sampling, not extraction of codec I-frames.

Three-camera configuration: `SED_1_Multi_Camera/configs/3_cameras.json`.
The existing mapping schema is preserved. `sampling_fps: 5.0` records the original
SED-1 baseline target and is deprecated by the new deterministic sampler.
The simulated inputs retain native frame rates, resolutions and original frames;
camera names represent intended roles, not installed factory camera evidence.

Use the existing Python 3.12 CPU environment:

```powershell
& ESE_CPU1_Quantization/runtime/venv/Scripts/python.exe SED_1_Multi_Camera/scripts/stream_manager.py --config SED_1_Multi_Camera/configs/3_cameras.json --test-duration 180
& ESE_CPU1_Quantization/runtime/venv/Scripts/python.exe -m unittest SED_1_Multi_Camera.tests.test_stream_manager
```

The original baseline must run **before refactoring SED-1**. To reproduce it
later, check out the saved baseline commit in an isolated folder and copy this
task's benchmark/config there; supply the same ignored source model and media.
It is intentionally not a parallel legacy implementation in production.

The benchmark uses the actual default `Backend/best.pt`, PyTorch FP32, 640 pixels,
three effective torch threads (Ultralytics' CPU initialization), one OpenCV thread
and shared micro-batches. CPU1 formats failed
their own gates and were never promoted to the default runtime. No backend is
substituted to manufacture a passing ingestion result. Baseline and optimized
run on the same local videos paced at native FPS. A full wall-clock 180-second
capture window is measured; shutdown drain is reported separately. CPU samples
exclude priming and shutdown. System CPU and process CPU divided by logical CPUs
are both reported on a 0–100% machine scale. The task's 95% is reference only.

Reports and the explicit acceptance verdict are in
`SED_1_Multi_Camera/reports/ESE_CPU2/ESE_CPU2_Benchmark_Report.md`.
The official CLI exits 2 if the run completed but measured targets failed;
it still writes all reports. Smoke/baseline phases are diagnostic runs.
Model throughput may be insufficient for all selected frames on this laptop;
every unread selected overwrite remains a real overrun/application loss.
Skipped frames never advance tracking or confirmation. RTP network packet loss
is not observable via this abstraction. Actual RTSP testing requires endpoints.

## Offline delivery

Exactly two task commits are saved on `feature/atlantis-async-rtsp`, based on the
completed local CPU1 branch. No push or PR is attempted while access is revoked.
After permission returns, from the repository root:

```powershell
git push -u origin feature/atlantis-async-rtsp
```

Or run `ESE_CPU2_Async_RTSP/sync_when_access_returns.ps1`. Normal push preserves
both commit IDs, does not force, and sets upstream only when the remote branch
actually exists. The actual renamed remote is `devlogixtechnology/industirx`.
If access returns to a different URL, update origin before running the command.

`python -m ESE_CPU2_Async_RTSP.offline_backup` saves and verifies a Git bundle,
then actually clones it and checks the saved branch HEAD. A separate ignored ZIP
preserves source checkpoint, three local videos and MLflow state with per-file
SHA256 verification. Keep the `backups` folder outside this disk as well if desired.
Restoring code: `git clone --branch feature/atlantis-async-rtsp <bundle-path> <new-folder>`.
Restore the runtime ZIP into that clone to recover the model, videos and run state.
The restored clone initially uses the local bundle as origin. Before syncing it:

```powershell
git -C <new-folder> remote set-url origin https://github.com/devlogixtechnology/industirx.git
git -C <new-folder> push -u origin feature/atlantis-async-rtsp
```

Python environments are not bundled; install the task requirements into a CPU
environment when restoring to a different workstation.
