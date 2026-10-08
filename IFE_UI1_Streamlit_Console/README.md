# IFE-UI1 — existing Streamlit multi-stream console

Production presentation remains `Frontend/app.py`. FastAPI owns capture, the CPU2
15-frame raw ring and 1-in-4 sampler, verified CPU1 INT8 inference, ByteTRACK,
15 evaluated-observation confirmation and SED-2 escalation. This folder contains
validation and offline delivery tools, not another inference application.

From repository root, start the existing backend in a separate terminal:

```powershell
ESE_CPU1_Quantization/runtime/venv/Scripts/python.exe -m uvicorn Backend.main:api_app --host 127.0.0.1 --port 8000
streamlit run Frontend/app.py --server.port 8501
```

Open `http://127.0.0.1:8501/` and press **Start three feeds**. The UI requests
`engine=openvino&device=cpu&imgsz=640&persist_frames=15`. Selected CPU1 XML/BIN
and metadata hashes are checked by the existing CPU3 adapter. Startup fails
explicitly if the artifact cannot be verified. Image upload still uses `/predict`
and the existing checkpoint. CPU1 accuracy/size and CPU3 throughput shortfalls
remain documented in their original reports; UI delivery success does not
promote or requalify the model.

The existing environment uses Python 3.12 for inference and installed Python
3.14/Streamlit 1.63 for presentation. Frontend dependencies remain in
`Frontend/requirements.txt`; benchmark-only dependencies are listed here.
`.streamlit/config.toml` disables usage analytics. Assets are served locally.
For local-only binding add `--server.address 127.0.0.1` to Streamlit.

The three existing native-rate video sources loop independently. Camera labels
are deployment roles; they are documentary, hazmat-exercise and rooftop-worker
stand-ins, visibly marked **SIMULATION**. Focus classes use the actual model's
12-class mapping. `chemical hazard` is the supported class. Forklift proximity
has no model class or SED-2 rule and is explicitly unavailable. No detections
are fabricated when a scene contains none of its configured focus classes.

Transport is three independent acknowledgement-paced binary WebSockets at
`/cameras/{camera_id}/live`. Each message is a network-order uint32 metadata
byte count, UTF-8 JSON, then JPEG. Original pixel XYXY coordinates accompany
the resized JPEG. One latest native frame per camera and one message in flight
per connection bound display memory. The browser retains at most 1,200 timing
samples, 300 telemetry/state/error entries and 300 seen track IDs per camera.
Generation plus raw-frame ID prevents restart/order confusion. Backend raw
detections provide real visual boxes while matched calibrated detections carry
authoritative track IDs and confirmation metadata. The UI does not loosen
alert thresholds or generate tracking identities.

CPU and RSS are from the **backend process**, using the existing SED-3 monitor;
RAM units are MiB, CPU is system utilization, FPS is completed evaluated frames
over a rolling five-second window. Inference capacity and capture FPS are not
advertised as operational FPS. `/system/status` reports the active engine and
privacy basis. Cloud 0% requires local video sources, local deployment, no
declared external services, and a loopback frontend/backend origin. Set
`DEPLOYMENT_MODE` and `RUNTIME_EXTERNAL_SERVICES` truthfully for deployments.
Unknown/external sources or services suppress the 0% claim. Remote local-network
cameras are conservatively unverified. Do not expose RTSP credentials in URLs
shown to operators; camera listings hide non-local sources.

Each canvas updates without rerunning Streamlit. Telemetry/alerts refresh once
a second, sockets reconnect with bounded exponential backoff, and no new frame
for three seconds produces **STALE**, never LIVE. Backend failure replaces
telemetry/privacy claims with unavailable values. SED-2 safety status and event
severity use actual backend responses. Geofences, when provided, are normalized
polygons; all geofence decisions remain in the backend. IoT remains simulated.

Run validation separately from ordinary unit tests:

```powershell
ESE_CPU1_Quantization/runtime/venv/Scripts/python.exe -m IFE_UI1_Streamlit_Console.run_checks
ESE_CPU1_Quantization/runtime/venv/Scripts/python.exe -m IFE_UI1_Streamlit_Console.benchmark --duration 180
```

The benchmark needs free ports 8000/8501 and installed Edge. It launches a fresh
headless browser context and only owned services, records a genuine 180-second
three-feed run, screenshots desktop/tablet/mobile, then exercises isolated
camera transport loss, actual stop/start controls, actual backend outage and
restart. Production frames/boxes are never mocked in this run. Fast deterministic
wire tests are labeled separately. The latency metric is backend result-ready
to completion of browser JPEG decode and canvas bitmap/overlay update, with
clock alignment/uncertainty recorded. Physical paint/scan-out is not measured.
Capture-to-canvas age and inference pipeline timing are reported separately.

Evidence: `Frontend/reports/ife_ui1_metrics.json`, CSV samples, screenshots and
`Frontend/reports/IFE_UI1_UI_Benchmark_Report.md`. Actual acceptance is evaluated
from those measurements, not assumed from the target.

## Exactly two task commits and later sync

Branch `feature/atlantis-streamlit-ui` was created from the completed CPU3 HEAD
`d071e197c6c69835cf11109a7c5a357339c69234`. It retains required earlier local task
history and isolates these two new UI commits from other task branches. The
renamed organization origin is `https://github.com/devlogixtechnology/industirx.git`.
No push or PR is attempted while access is revoked.

After access returns, from repository root:

```powershell
& .\IFE_UI1_Streamlit_Console\sync_when_access_returns.ps1
# Equivalent: git push -u origin feature/atlantis-streamlit-ui
```

This is a normal push; no force push or history rewrite. The complete-history
bundle and verified local runtime ZIP are under this task's ignored `backups/`.
They preserve both commits and required untracked weights, clips and local
MLflow artifacts. Restore elsewhere with:

```powershell
git clone --branch feature/atlantis-streamlit-ui <bundle-path> recovered-industirx
git -C recovered-industirx remote set-url origin https://github.com/devlogixtechnology/industirx.git
# Extract the runtime ZIP into recovered-industirx; recreate environments.
```

Do not merge/overwrite an existing checkout when restoring. Backups are local
recovery artifacts and are not staged in Git. `offline_backup.py` verifies bundle
restore HEAD, ZIP CRCs and every archived file's SHA-256.
