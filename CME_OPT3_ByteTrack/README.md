# CME-OPT3: ByteTRACK temporal alert filtering

The task is implemented in this separate folder and integrated into the existing
`Backend/main.py` and SED-1 scheduler. It uses the selected CME-OPT2 detector
`cme-opt2-focal-cosine-12class-v1` at `Backend/best.pt`, SHA256
`c4aba081f6357e23a7370a5f7cf98eff2c6faa0c4c20a2d4dcb8bcabdd490061`.
It performs no detector training. That detector still has the documented
CME-OPT2 chemical accuracy shortfall; temporal tracking cannot repair misses.

## Pipeline

Shared batched YOLO detection → existing CME-2 confidence thresholds → upstream
ByteTRACK association → camera geofences → one track-aware temporal stage →
confirmed SED-2 severity/escalation/actions. The old CME-2 3-of-5 stage is
replaced in this path; it is not applied before another 15-frame filter.
Legacy `AlertPolicy` remains available for old tests and a fair benchmark
baseline. Confidence thresholds are unchanged: chemical/fire/no-helmet .25,
smoke/water-leak .50, remaining classes .25.

Ultralytics **8.4.24**, `ultralytics.trackers.byte_tracker.BYTETracker.update`,
project config `Backend/configs/bytetrack.yaml`, assignment dependency
`lap==0.5.13`. The documented lower-level API preserves a shared YOLO model and
SED-1 micro-batching while applying confidence before association; creating
separate `model.track()` models per camera would duplicate inference resources.
See the [official tracker reference](https://docs.ultralytics.com/reference/trackers/byte_tracker/).
Each camera owns a policy instance and each semantic class has a separate
upstream tracker to prevent class-agnostic cross-class association. A lock
preserves the upstream process-global ID allocator during tracker construction.
Downstream identity includes camera, raw track ID, class, geofence and a unique
incident ID. This supports simultaneous same-class violations and fresh
incidents after clearing. It does not implement cross-camera re-identification.

Actual detector classes: baekra, color issues, contamination, cut, gray stitch,
selvet, stain, chemical hazard, fire, no helmet, smoke, water leak. All supported
boxes receive IDs when ByteTRACK associates them. There are no person or
machinery classes in these weights; none are invented. Amorphous hazards may
fragment. There is no spatial fallback that merges independent tracks or
counts missing detections as positive frames. MOT identity ground truth is
unavailable for the public benchmark, so ID switches remain unmeasured.

## Temporal state and lifecycle

`CANDIDATE → CONFIRMED → ACTIVE → CLEARED/EXPIRED`.
The default `persist_frames=15` is defined centrally and can be overridden
explicitly by CLI or `/streams/start`. Only a qualifying, observed detection
advances its own history once per evaluated frame. Raw source-frame gaps caused
by sampling do not count as additional frames. A missed evaluated detection or
geofence exit resets an unconfirmed consecutive count to zero. Lost Kalman
predictions never advance it. Duplicates, ID changes, class changes and other
cameras cannot combine counts. Non-increasing frame indices require a stream
reset and are rejected rather than double-counted.

Frame 15 emits one formal alert; subsequent observations update the same
confirmed event. Brief misses preserve its incident identity until the existing
per-class `clear_frames` (5) expire. Candidate/track state is removed then;
SED-2 keeps its existing 5/6-second absence-resolution policy and archives the
event. New incidents receive new IDs. Stream ends, restarts and file loop
boundaries reset tracker/confirmation state and resolve the prior stream's
active SED-2 events. Active SED-2 identity entries are removed on resolution.
Shutdown must finish capture and inference before a replacement session starts.
Candidates never enter severity or trigger mock IoT shutdown.

The new stream endpoint defaults its sampling target to 10 FPS, overriding the
old camera YAML's 5 FPS when started through this endpoint. Actual throughput
is reported; target FPS is not guaranteed. Fifteen frames occupy about 1.5s at
10 FPS (the first-to-fifteenth observation spans about 1.4s). At 5 FPS they take
about 3s, so that cadence cannot demonstrate the two-second target. CPU smoke
throughput is about 2.13 FPS and also cannot meet the real-time latency gate.

## Backend and dashboard

```powershell
python Backend/main.py --source data/test_factory_clip.mp4 --tracker bytetrack.yaml --persist-frames 15 --device cpu
python Backend/main.py --help
uvicorn Backend.main:api_app --host 127.0.0.1 --port 8000
```

The basename `bytetrack.yaml` resolves to the project-owned copy. CLI options
also include `--evaluated-fps`, `--output`, `--conf`, and `--debug-tracker`.
CLI output is JSONL with existing detection fields plus track IDs, confirmation
status, frame count and required count, timestamps and SED-2 events.
The ordinary CLI is an offline video processor: its media-time confirmations
are not a claim of live wall-clock latency. Use the paced benchmark for that.

Single-image `/predict` stays stateless by default. Sequential clients can use
`apply_alert_policy=true`, stable `camera_id`, increasing `frame_index` and
`timestamp_sec`; `reset_tracker=true` begins a new session. It exposes the same
track-aware confirmation result. Upload camera sessions are bounded at 64.
The Streamlit monitor shows camera/class/track/confidence and candidate progress
or confirmed state without changing the existing severity/action controls.

## Benchmark reproduction

The expected private/project `data/test_factory_clip.mp4` was absent. The
recorded benchmark uses a licensed historical textile-factory film and an MP4
derivative of its first continuous 600 seconds. The cached derivative can be
copied to that ignored path for the exact backend interface above. See
[`annotations/README.md`](annotations/README.md) for attribution, review method
and limitations. This is a factory-domain audit, not verified modern CCTV.
Ground truth is manually reviewed scene-level worker-without-hardhat intervals,
not detector predictions; onset uncertainty is up to one second. False alerts
match class and the actual interval with zero temporal tolerance. All missed
and slow events are reported. Reduction is unavailable if baseline false alerts
are zero. The conservative latency gate includes annotation uncertainty.

```powershell
$env:PYTHONIOENCODING = 'utf-8'
python -m CME_OPT3_ByteTrack.prepare_inputs
python -X utf8 -m modal run --detach CME_OPT3_ByteTrack/modal_runner.py
python -m CME_OPT3_ByteTrack.fetch_artifacts
python -m CME_OPT3_ByteTrack.verify
python -m CME_OPT3_ByteTrack.plot_results
python -m CME_OPT3_ByteTrack.finalize
python -m unittest discover -s Confidence_Calibration/tests -v
python -m unittest discover -s SED_1_Multi_Camera/tests -v
python -m unittest discover -s SED_2_Alert_Escalation/tests -v
python Experiment_Tracking/scripts/validate_registry.py
```

The benchmark evaluates both the real calibrated CME-2 3-of-5 baseline and the
new track-aware filter on identical predictions, weights, resolution, confidence
thresholds, full-frame geofence, cadence and severity rules. It measures shared
detector time separately from baseline/tracker/escalation overhead. The paced
run measures monotonic confirmation time against source event occurrence times.
It retains alert CSVs, every event latency, frame counts, cleanup statistics,
summary and terminal output; acceptance comes only from actual results.

Modal volume `industirx-cme-opt3` retains ignored video/weights and reports.
Existing CME-3 MLflow tracking uses the original helper and shared
`Vision-Driven-Industrial-Safety` experiment on the existing CME-OPT2 volume.
GPU min_containers=0 and scaledown_window=600; the existing utilization watchdog
terminates the same worker PID after continuous 600-second zero utilization,
including storage preparation. The function exits when work completes. Inputs
are verified on CPU before allocating GPU resources. Video transcoding is CPU
work and preserves both comparison paths' identical input bytes.

Numerical and operational acceptance is recorded in
[`reports/CME_OPT3_Benchmark_Report.md`](reports/CME_OPT3_Benchmark_Report.md).
Historical-source and annotation limitations must remain visible even if a
controlled numerical check passes. No previous task/model/policy history is
overwritten; the new alert policy is `cmeopt3-bytetrack15-v1`.
