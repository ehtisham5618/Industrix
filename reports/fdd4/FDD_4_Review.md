# FDD-4 — Cinematic Product Demo Video Recording: Review

**Status: IMPLEMENTED — REVIEW BLOCKED** (the real demo video is recorded, verified and committed; review is
blocked only by items outside this task: GitHub Actions has never run, no voice narration was requested/produced,
and physical offline operation is untested).

## Recorded deliverable
`reports/fdd4/demo/industrix_demo_20261022T175557Z.mp4` — 132.37 s, 1920×1080, H.264, 30 fps, no audio,
5,354,545 bytes, full ffmpeg decode clean, SHA256 in `recording_20261022T175557Z.json`. Twelve scenes:
title → about → live dashboard → textile card → **real textile inference (baekra 95.0%)** → safety card →
**real fire inference (fire 81.7%, smoke 40.0%, smoke 32.5%)** → API card → real `/health` → real
`/system/status` → incident history + edge health ("LOCAL ONLY — CLOUD DISABLED") → closing card.
Keyframes: `reports/fdd4/demo/frame_scene01.png` … `frame_scene12.png` (inspected).

## How it was made
`python -m FDD_4_Demo.record_demo`: preflight (ffmpeg/ffprobe, Playwright, model, assets) → EAP-5 watchdog start →
headless Edge at 1920×1080 with Playwright live recording → real uploads and clicks in the Streamlit UI → watchdog
stop (always) → ffmpeg H.264 export under a temporary name, renamed only when complete → ffprobe + full decode
verification → keyframe extraction. Non-loopback browser requests are blocked and logged (0 in the final take).
Real time: no speed-up, no edited or drawn detections; caption cards are local HTML with factual text.

## Takes
1. Recorded, superseded: `/docs` blank (Swagger UI loads from cdn.jsdelivr.net, blocked offline); tables and the
   incident panel captured mid-render.
2. Failed cleanly: upload control not rendered within 30 s (render waits added; Playwright errors now reported as
   RECORDING FAILED); services stopped; nothing overwritten.
3. Final (above).

## Validation
- `pytest FDD_4_Demo/tests -v -rs`: **18 passed** (manifest/preflight validation, output protection, export
  verification with real ffmpeg-generated videos incl. wrong resolution and corrupt files, offline guard, evidence
  consistency incl. SHA256 of the committed video).
- Full repository suite (`repository_pytest_output.txt`, run before the 18th FDD-4 test was added): 661 passed, 2 failed, 12 skipped. Both failures are the pre-existing ESE-CPU1 INT8 baseline gates (measured IR size 11,773,383 B vs the 6.5 MB gate; mAP drop 1.03 pp vs the 1.0 pp gate); no FDD-4 failure.
- UI-observed click-to-results: 6.2 s (textile) and 2.8 s (fire) under recording load. Service startup time was not captured correctly for take 3 (the recorder measured it after the recording ended, 226.0 s, which is wrong); the recorder now reports `healthy_after_watchdog_start_s`. Scene times are recorder-clock times; the video timeline drifts from them by about -2 s to +5 s, so keyframes for take 3 were picked by inspecting the video and later takes save live page screenshots.
  These are observations, not benchmarks; no latency or memory SLA exists.

## Exclusions and limitations
Live multi-camera streaming (≈2.5 fps on this CPU), FastAPI `/docs` (not offline), PDF export (no confirmed
incident), and any accuracy/latency claims are excluded. Captions only. `/system/status` JSON is small on screen.
The textile box spans the image, so its in-image label is outside the frame (app rendering, not edited).
