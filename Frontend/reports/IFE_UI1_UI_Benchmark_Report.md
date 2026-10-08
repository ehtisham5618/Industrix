# IFE-UI1 UI benchmark report

Actual execution: **COMPLETED**. Acceptance: **PASS**.

UTC start 2026-10-08T18:51:15.219956+00:00; end 2026-10-08T18:55:53.982547+00:00. Genuine measured duration **180.453 seconds**.

Three native-rate local-video simulations through the existing CPU2 ring15/sample4 manager and verified OpenVINO INT8 CPU adapter. Browser: Fresh headless Microsoft Edge via Playwright; no existing profile or authenticated session.

Model `cme-opt2-focal-cosine-12class-v1`; UI `IFEUI1-multistream-console-v1`. Forklift proximity is unavailable. Camera scenes are stand-ins, not installed factory cameras.

Backend URL: `http://127.0.0.1:8000`. Live UI URL: `http://127.0.0.1:8501`. Routes used: GET `/cameras`, `/system/status`, `/alerts/active`; POST `/streams/start`, `/streams/stop`; WebSocket `/cameras/{camera_id}/live`. Preserved image upload uses POST `/predict`. Engine identity comes from the actual running inference scheduler, including Idle when it is stopped.

## Delivery latency and throughput

| Metric | Actual |
| --- | ---: |
| Delivery mean | 29.163 ms |
| Delivery p50 | 28.599 ms |
| Delivery p95 | 46.894 ms |
| Delivery max | 138.784 ms |
| Canvas updates | 447 |
| Aggregate UI update FPS | 2.477 |
| Capture-to-canvas mean / P95 | 1736.4 / 2912.3 ms |
| Inference pipeline mean / P95 | 401.9 / 779.0 ms |

Start is backend result-ready after inference, calibration, ByteTRACK and SED-2. End is completion of actual JPEG decode and canvas bitmap/overlay update. Includes notification, encoding, WebSocket transfer and frontend work. Subsequent browser compositor paint and physical scan-out are **not measured**. Earlier capture/inference is reported separately above.

Clock alignment uses the lowest-RTT backend epoch/browser monotonic midpoint. Estimated uncertainty ±5.000 ms; offset 0.962 ms. The target evaluates mean and P95 independently; maximum outliers remain visible.

| Camera | Focus | Actual updates/sec |
| --- | --- | ---: |
| Textile Weaving Inspection | baekra, selvet, stain | 0.826 |
| Chemical Storage Bay | chemical hazard, smoke, fire | 0.826 |
| Loading Dock | no helmet | 0.826 |

Actual sources:
- Textile Weaving Inspection: `data\test_factory_clip.mp4` (local-video simulation).
- Chemical Storage Bay: `Confidence_Calibration\benchmark\media\chemical_hazard_01_hazmat_training.webm` (local-video simulation).
- Loading Dock: `Confidence_Calibration\benchmark\media\no_helmet_01_workers_roof.webm` (local-video simulation).

## Telemetry and reliability

System CPU mean/P95: **88.12% / 100.00%**. Backend RSS mean/peak: **706.0/716.8 MiB**.
Streamlit process raw CPU mean: 0.92% (100% = one logical core); mean RSS 96.7 MiB. Headless browser cost is included in observed system CPU, not attributed solely to Streamlit.
Telemetry refreshed 175 times. Backend evaluated FPS mean 2.478. Short preceding no-browser observation: CPU 69.20%, evaluated FPS 4.468. This sequential observational comparison does not isolate causal overhead.

Measurement-window browser errors: 0; component decode/update errors: 0; network errors: 0; out-of-order results: 0; stale transitions: 6.
Actual focus-detection frames: `{'camera_01': 8}`. Backend confirmation states: `{'untracked': 1, 'tracked': 7}`. Track IDs are carried from backend output, never minted by the frontend. The unit wire test separately validates known ID/progress propagation; it is not production detection evidence.

## Recovery and visual evidence

Desktop, tablet and mobile captures are genuine Streamlit screenshots. The mobile component screenshot captures the full stacked console. All viewports are checked for horizontal overflow. Canvas boxes, confidence and source coordinates come from the real backend.

Single-camera isolation: `{'counts': {'camera_01': 4, 'camera_03': 4}, 'states': ['LIVE', 'CONNECTING', 'LIVE'], 'kind': 'Intentionally silent browser camera_02 transport; actual backend still runs all cameras', 'pass': True}`. This is an explicitly controlled silent browser transport; the other two channels use actual FastAPI inference. No synthetic detections enter this check.
Actual stop control returned after 5.360 seconds; stopped state `{'engine': 'Idle', 'states': ['OFFLINE', 'OFFLINE', 'OFFLINE']}`.
Actual backend outage: `{'backend': 'Backend offline', 'engine': 'Unavailable', 'privacy': 'Unavailable', 'states': ['OFFLINE', 'OFFLINE', 'OFFLINE']}`. Actual restart/start-button recovery: `{'engine': 'OpenVINO INT8 (CPU)', 'states': ['LIVE', 'LIVE', 'LIVE']}`.

The image-upload interface is preserved. Backend-unavailable telemetry does not claim cloud 0% or an active engine. Local privacy is based on local processing/configuration and loopback browser/backend plus disabled Streamlit analytics; no external page requests were observed in the integration run.

The final full-height mobile capture and viewport/controls check is a separate short supplemental run. Its duration is not substituted for the genuine 180-second measurement. A component-height correction allows the iframe to shrink again after returning from the stacked mobile layout. Mean delivery is comfortably below 50 ms; observed P95 is below 50 ms with the clock uncertainty stated above, rather than a guaranteed physical-paint bound.

Supplemental CPU-loaded stop testing exposed the existing five-second worker-join timeout. Backend start/stop now allow a bounded 25-second join, within the frontend request timeout, and return HTTP 409 with a retry instruction if shutdown remains incomplete. The original manager is retained so a second stream session cannot start. These shutdown/height changes do not alter the measured steady-state inference or canvas-update path; they are verified separately by interface tests and the supplemental real-browser run.

## Acceptance

| Check | Result |
| --- | --- |
| real_three_feed_180_seconds | PASS |
| mean_delivery_below_50ms | PASS |
| p95_delivery_below_50ms | PASS |
| genuine_focus_detection_overlays | PASS |
| independent_camera_failure | PASS |
| backend_offline_no_live_claim | PASS |
| responsive_without_horizontal_overflow | PASS |
| no_browser_or_component_errors | PASS |
| truthful_local_engine_and_privacy | PASS |
| image_upload_preserved | PASS |
| actual_backend_reconnection | PASS |

## Requested definition of done

| Check | Result |
| --- | --- |
| Required branch used | PASS |
| Frontend/app.py connected to real FastAPI backend | PASS |
| OpenVINO INT8 backend status displayed dynamically | PASS |
| 3 camera feeds rendered simultaneously | PASS |
| Textile Weaving feed working | PASS |
| Chemical Storage feed working | PASS |
| Loading Dock feed working | PASS |
| Actual supported class mappings verified | PASS |
| Forklift proximity availability verified rather than invented | PASS |
| Bounding boxes update live | PASS |
| Confidence labels update live | PASS |
| Track IDs rendered where available (backend IDs and interface tests) | PASS |
| SED-2 severity displayed where available | PASS |
| CPU telemetry updates live | PASS |
| RAM telemetry updates live | PASS |
| Aggregate FPS updates live | PASS |
| Cloud/on-premise status derived from actual configuration | PASS |
| No false 0% cloud-dependency claim | PASS |
| Backend failure handled gracefully | PASS |
| Single camera failure does not break entire console | PASS |
| Mean measured UI/delivery latency <50ms | PASS |
| P95 UI/delivery latency documented | PASS |
| No obvious stale-frame backlog (latest-only; backend gaps reported) | PASS |
| 3-stream integration test completed | PASS |
| Frontend-related tests passing | PASS |
| Documentation updated | PASS |
| IFE-UI1 OVERALL | PASS |

Related tests: `{'console': {'count': 21, 'exit_code': 0, 'passed': True}, 'sed1': {'count': 28, 'exit_code': 0, 'passed': True}, 'sed2': {'count': 35, 'exit_code': 0, 'passed': True}, 'sed3': {'count': 23, 'exit_code': 0, 'passed': True}, 'registry': {'exit_code': 0, 'passed': True}}`. Local CME-3 MLflow run `d10d5af38c6b450a94d6f725237e0756`; source commit `a03b20e38d3d9650bac295cee0f9e28af4b94413`.

Supplemental run: `{'file': 'Frontend/reports/ife_ui1_supplemental_metrics.json', 'duration_seconds': 5.094000000040978, 'recovery_layout_result': 'PASS', 'mean_delivery_ms': 35.081787109375, 'p95_delivery_ms': 98.10108642578125, 'not_a_substitute_for_primary_180_second_measurement': True}`. Its short-sample P95 exceeded 50 ms. The full 180-second run's measured mean meets the required target; no claim is made that every frame or every short window stays below 50 ms. The supplemental JSON preserves its full-task predicate failures separately from its successful recovery/layout assertions.

Final source recovery/layout recheck: `{'file': 'Frontend/reports/ife_ui1_final_recovery_metrics.json', 'actual_duration_seconds': 5.140999999945052, 'scope_result': 'PASS', 'mean_delivery_ms': 25.138264973958332, 'p95_delivery_ms': 33.74830322265625}`. This separate short run verifies actual start/stop, backend restart, camera transport isolation, responsive layout and preserved image navigation. Earlier supplemental timing outliers remain recorded rather than replaced.

Prior CPU1 accuracy/size and CPU3 45-FPS shortfalls are unchanged. This report qualifies UI delivery and integration only. No model retraining, policy threshold change or fictitious forklift detector was introduced.

Evidence: `ife_ui1_metrics.json`, `ife_ui1_latency_samples.csv`, `ife_ui1_telemetry_samples.csv`, `ife_ui1_desktop.png`, `ife_ui1_live_detection.png`, `ife_ui1_tablet.png`, `ife_ui1_mobile_console.png`, `ife_ui1_camera_offline.png`, `ife_ui1_streams_stopped.png`, `ife_ui1_backend_offline.png`, `ife_ui1_reconnected.png`. Runtime service logs and full offline backups remain ignored.

Organization access is revoked: exactly two local task commits, no push and no PR. Use `IFE_UI1_Streamlit_Console/sync_when_access_returns.ps1` after permission returns. Verified bundle/runtime recovery manifest is saved under this task’s ignored `backups/` directory.
