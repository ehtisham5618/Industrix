# IndustriX Product Demo — Storyboard and Script

Version `fdd4-demo-v1` · source of truth: [`FDD_4_Demo/demo_manifest.json`](../../FDD_4_Demo/demo_manifest.json) ·
recorded take: `reports/fdd4/demo/industrix_demo_20261022T175557Z.mp4` (132.4 s, 1920×1080, H.264 30 fps, no audio).

Narration is delivered as on-screen caption cards (no voice track). Every product scene is a live
capture of the real dashboard/API; scene times below are recorder-clock offsets (seconds since the page opened); the exported video drifts from them by about −2 s at the start to +5 s at the end, so a scene appears a little earlier or later in the MP4. Nothing is sped up,
and no detection was drawn or edited by the recorder: boxes, labels and tables are rendered by the app.

| # | Time (s) | Screen / action | On-screen text | Input | Observed in the recording | Verified |
|---|---|---|---|---|---|---|
| 1 | 0.0–6.3 | Title card | IndustriX: AI-assisted textile defect inspection and industrial safety monitoring; running locally on a CPU laptop, no cloud inference | — | card | yes |
| 2 | 6.3–14.4 | "What this demo shows" card | real dashboard + backend started by the watchdog; live inference by the 12-class YOLOv8s detector; health check and incident history; real time, nothing sped up or edited | — | card | yes |
| 3 | 14.4–≈32 | Operator dashboard, Live Monitor tab | — | — | Industrial Vision Console: engine Idle, backend RAM, cloud dependency 0%, three simulated camera cards (offline until feeds start) | yes |
| 4 | ≈27–32 | Card "Textile defect inspection" | uploading a fabric sample; backend returns classes, confidences, boxes | — | card | yes |
| 5 | 32.4–59.1 | Image Inference: upload textile sample → Detect Defects → annotated image → results table | — | `tests/assets/ife_ui3_textile.png` | **baekra 95.0%**, 1 detection; 6.2 s click-to-results (UI-observed) | yes |
| 6 | 59.1–64.2 | Card "Industrial safety" | the same detector covers fire, smoke, water leak, chemical hazard, no helmet; a detection is a prediction, not a confirmed incident | — | card | yes |
| 7 | 64.2–85.0 | Image Inference: upload fire sample → Detect Defects → annotated image → table | — | `tests/assets/ife_ui3_fire.png` | **fire 81.7%, smoke 40.0%, smoke 32.5%**; 2.8 s click-to-results | yes |
| 8 | 85.0–89.1 | Card "Local API" | health, readiness and status on 127.0.0.1; model checksum verified at startup | — | card | yes |
| 9 | 89.1–95.2 | `GET /health` | — | — | `{"status":"ok","model_loaded":true,…,"model_sha256":"c4aba081…","classes":12}` | yes |
| 10 | 95.2–102.3 | `GET /system/status` | — | — | engine, telemetry, privacy (local, cloud 0%), the 12 model classes (raw JSON, small text) | yes |
| 11 | 102.3–119.6 | Live Monitor → Incident History, quality alarms, edge health | — | — | "No formally confirmed incidents have been logged"; edge panel "LOCAL ONLY — CLOUD DISABLED" | yes |
| 12 | 119.6–127.6 | Closing card | real-time dashboard inference for textile defects and safety hazards; local-only, supervised services; predictions need operator review; no performance targets claimed | — | card | yes |

The exported video is 132.4 s: the capture also includes the browser's first page load before scene 1
and the time to close the page after scene 12.

## Deliberately excluded
- Live three-camera streaming: it needs the IFE-UI3 demo media and fixture setup and runs at about 2.5 fps
  aggregate on this CPU (ESE-CPU3); not shown, to avoid implying real-time multi-camera performance.
- FastAPI `/docs` (Swagger UI): it loads assets from a public CDN and renders blank offline (found in take 1).
- PDF incident export: no confirmed incident exists in the local database to export.
- Accuracy, latency or memory claims: no approved targets exist (see the hardware sizing guide).
