Reproducible recording of the real IndustriX product, with the final 1080p demo video.

**Video:** `reports/fdd4/demo/industrix_demo_20261022T175557Z.mp4` — 132.4 s, 1920×1080, H.264 30 fps, 5.35 MB, no audio (caption cards), full decode verified. Scenes: dashboard, real textile inference (baekra 95.0%), real fire inference (fire 81.7%, smoke 40.0%/32.5%), `/health`, `/system/status`, incident history, title/closing cards. Keyframes in `reports/fdd4/demo/`.

**What changed**
- `FDD_4_Demo/record_demo.py` + `demo_manifest.json`: preflight, watchdog-managed real services, Playwright/Edge 1080p live capture, offline request guard (0 blocked in the final take), always-stop services, timestamped never-overwrite export, ffprobe/decode verification, keyframes, recording report
- `docs/demo/INDUSTRIX_DEMO_STORYBOARD.md`, `docs/demo/RECORDING_GUIDE.md`; 18 tests; CI job `demo-recorder`

**Findings:** FastAPI `/docs` is not offline-capable (Swagger UI from a CDN), so that scene was replaced; take 2 exposed a UI render race (fixed). Click-to-result times are UI observations under recording load, not benchmarks.

**Not verified:** voice narration (not produced), physical offline, GitHub Actions. No application or model changes.
