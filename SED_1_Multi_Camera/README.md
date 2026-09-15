# SED-1 Multi-Camera Stream Architecture

Current ingestion is **ESECPU2-async-ring15-sample4-v1**: independent capture
workers, fixed 15-slot raw rings and zero-based 1-in-4 sampling. Only selected
frames reach shared inference and CME-OPT3's 15 evaluated-observation confirmation.
The original queue/CME-2 description below is historical. FastAPI accepts old
`queue_size`/`evaluated_fps` parameters for compatibility and reports the effective
fixed ring size 15 and sampling factor 4. `sampling_fps` in old YAML files is
deprecated by raw-frame sampling. Local files now play at native FPS and loop
with session resets. RTSP/HTTP sources use native FFmpeg open/read deadlines and
cancelable reconnects; USB is selected by a numeric source string.

See [CPU2 task tools](../ESE_CPU2_Async_RTSP/README.md) and
[measured acceptance report](reports/ESE_CPU2/ESE_CPU2_Benchmark_Report.md).
To run the three-camera benchmark from the repository root:

```powershell
python SED_1_Multi_Camera/scripts/stream_manager.py --config SED_1_Multi_Camera/configs/3_cameras.json --test-duration 180
```

Use a Python environment with the task requirements installed. Configure private
live sources with `source_env` pointing at a local environment variable;
committed configs contain no secrets.

SED-1 extends the existing single-stream detector into a concurrent 1-4 camera
pipeline for industrial monitoring demos.

## Architecture

```mermaid
flowchart LR
  C1[Camera 1] --> W1[Capture Worker]
  C2[Camera 2] --> W2[Capture Worker]
  C3[Camera 3] --> W3[Capture Worker]
  C4[Camera 4] --> W4[Capture Worker]
  W1 --> Q[Bounded Latest-Frame Queues]
  W2 --> Q
  W3 --> Q
  W4 --> Q
  Q --> S[Fair Scheduler + Micro-Batch]
  S --> D[Shared YOLO Detector]
  D --> G[Per-Camera Geofence Filter]
  G --> A[CME-2 Per-Camera AlertPolicy]
  A --> R[Camera-Specific Results and Alerts]
```

The detector is shared. Each camera has its own capture worker, queue, geofence
configuration, metrics, and CME-2 `AlertPolicy` instance, so temporal histories
and alerts never leak across cameras.

## Configuration

Camera configuration lives in:

```text
SED_1_Multi_Camera/configs/cameras.yaml
```

Each camera declares a source video, monitored classes, and one or more
normalized polygon geofences. A detection is inside a geofence when its
bounding-box center falls inside the polygon.

Benchmark defaults live in:

```text
SED_1_Multi_Camera/configs/benchmark.yaml
```

## Running Benchmarks

From the repository root:

```powershell
python SED_1_Multi_Camera/scripts/benchmark_multistream.py --streams 3 --duration-seconds 60 --warmup-seconds 5 --device 0
```

Useful options:

- `--streams 1|2|3|4`
- `--device cpu` or `--device 0`
- `--imgsz 640`
- `--queue-size 2`
- `--no-batch`

The script writes JSON and CSV outputs under:

```text
SED_1_Multi_Camera/reports/
```

Frame-drop rate is:

```text
unexpected frame drop rate = overload_drops / eligible_frames * 100
```

Configured sampling skips are reported separately.

## Demo API

The existing image endpoint remains:

```text
POST /predict
```

SED-1 adds:

```text
GET  /cameras
POST /streams/start
POST /streams/stop
GET  /cameras/{camera_id}/status
GET  /cameras/{camera_id}/latest
GET  /alerts
```

## Future Camera Sources

The source layer is isolated behind `CameraSource`. SED-1 implements file-backed
simulated cameras now; RTSP, USB cameras, or HTTP streams can be added by
implementing the same `open/read/close` interface.

## Current Local Benchmark Status

The checked-in report records a real local CPU benchmark. It validates execution
but fails the performance DoD because CUDA is unavailable on this machine. Run
the benchmark command above on the target GPU/T4 environment before marking
SED-1 performance as passed.
