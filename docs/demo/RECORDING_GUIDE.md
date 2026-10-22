# IndustriX Demo Recording Guide (FDD-4)

One command records the real product: `FDD_4_Demo/record_demo.py` starts the backend and dashboard with the
EAP-5 watchdog, drives the real Streamlit UI in headless Microsoft Edge through Playwright at 1920×1080 with
live page recording, uploads the bundled sample images for real inference, stops the services, and exports an
H.264 MP4 with ffmpeg. Storyboard: [INDUSTRIX_DEMO_STORYBOARD.md](INDUSTRIX_DEMO_STORYBOARD.md).

## Prerequisites (verified on Windows 11, 2026-10-22)
| Item | Check |
|---|---|
| Full-stack Python (backend + dashboard + `playwright`) | `ESE_CPU1_Quantization/runtime/venv` was used |
| Microsoft Edge (Playwright `channel="msedge"`) | `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe` |
| `ffmpeg` and `ffprobe` on PATH | `ffmpeg -version` (not downloaded automatically) |
| `Backend/best.pt` | `python -m FDD_3_Deployment_Handoff.validate_deployment` |
| Sample assets | `tests/assets/ife_ui3_textile.png`, `tests/assets/ife_ui3_fire.png` (in Git) |
| Ports 8000 and 8501 free | the watchdog refuses to start duplicates |

## Commands
```powershell
$py = 'ESE_CPU1_Quantization/runtime/venv/Scripts/python.exe'
& $py -m FDD_4_Demo.record_demo --dry-run          # manifest + preflight only (exit 0 / 2)
& $py -m FDD_4_Demo.record_demo                    # record, export, verify (about 4-5 minutes)
& $py -m FDD_4_Demo.record_demo --name site_demo --out-dir reports/fdd4/demo
& $py -m pytest FDD_4_Demo/tests -v -rs            # 18 tests
```
Exit codes: 0 recorded and verified · 1 recording/export/verification failed · 2 preflight failed.
Stop: Ctrl+C. The services are always stopped in a `finally` block, and an interrupted export never
receives the final file name.

## Outputs
| Path | Content |
|---|---|
| `reports/fdd4/demo/<name>_<UTC stamp>.mp4` | final export (timestamped; never overwritten) |
| `reports/fdd4/demo/recording_<stamp>.json` | SHA256, ffprobe metadata, decode check, actual scene timings, observed results, blocked requests |
| `reports/fdd4/demo/frame_<stamp>_sceneNN.png` | live page screenshot at the end of each scene (take 3 used `frame_sceneNN.png`, picked from the video by inspection) |
| `FDD_4_Demo/runtime/<stamp>/raw_capture.webm` | untouched source capture plus caption-card HTML (git-ignored) |

## Reviewing a take
1. Check the recording JSON: `verification.ok` true, 1920×1080, `decodes_cleanly` true, `external_requests_blocked` empty.
2. Inspect every scene screenshot for skeleton placeholders, unrendered icons, debug output or private data.
3. Play the MP4 end to end.

## Troubleshooting
| Symptom | Action |
|---|---|
| `PREFLIGHT FAILED: ffmpeg not found` | install ffmpeg and add it to PATH |
| `asset ... missing` / `Backend/best.pt missing` | restore the file; assets and weights are never downloaded |
| `watchdog start failed` / services not healthy | `python -m EAP_5_Watchdog status`, `EAP_5_Watchdog/runtime/logs/`; free ports 8000/8501 |
| `RECORDING FAILED: TimeoutError ...` | the UI did not render in time; rerun (take 2 failed this way before the render waits were added) |
| Blank page in a scene | an external asset was blocked: check `external_requests_blocked` |
| No audio | expected: captions only; add narration in an editor if required |

## Offline behaviour
Every browser request except `file:`, `data:`, `blob:` and loopback is aborted and logged. The final take
recorded **0 blocked requests**. Take 1 showed FastAPI's `/docs` needs `cdn.jsdelivr.net` (Swagger UI) and
`fastapi.tiangolo.com` (favicon), so the API docs page is not offline-capable; the scene was replaced by
`/system/status`. No physical network disconnection was performed.

## Takes on 2026-10-22 (all kept)
| Take | Result |
|---|---|
| 1 `industrix_demo_20261022T174723Z.mp4` | recorded (133 s) but superseded: blank `/docs`, results tables and incident panel captured mid-render |
| 2 | failed: file-upload control not rendered within 30 s; services stopped cleanly, nothing overwritten |
| 3 `industrix_demo_20261022T175557Z.mp4` | **final**: 132.4 s, 5,354,545 bytes, all scenes rendered, 0 blocked requests |

## Known limitations
- Captions only; no voice narration or music.
- `/system/status` is raw JSON in small type.
- The textile box hugs the image border, so its in-image label is drawn outside the visible area (app behaviour, not edited); the results table shows the class.
- The capture loads the CPU heavily (the edge panel shows system CPU 100% during recording); click-to-result times are UI observations under recording load, not benchmarks.
- Per-scene screenshot keyframes and the `healthy_after_watchdog_start_s` field were added after take 3 and have not yet been exercised by a full recording.
