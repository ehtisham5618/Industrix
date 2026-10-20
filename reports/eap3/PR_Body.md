Multi-stage CPU image for the FastAPI inference service, below the 1.8 GB gate with real inference.

**Image size (unpacked filesystem, decimal GB gate):** `bundled` 1,542,234,302 B (1.542 GB, weights included); `runtime` 1,507,953,786 B (weights mounted). gzip `docker save` 481 MB. `.Size` on the containerd store is compressed and is not used as the gate.

**What changed**
- `Dockerfile` (builder → runtime → bundled), `.dockerignore`, `compose.yaml`
- `EAP_3_Lightweight_Docker/`: pinned runtime requirements (CPU torch, headless OpenCV, polars omitted, pi-heif added), exact-byte size gate, 16 container tests
- `Backend/main.py`: `/health`, `INDUSTRIX_MODEL_PATH` / `INDUSTRIX_REQUIRE_MODEL` / `INDUSTRIX_MODEL_SHA256`, 400 for unreadable uploads, clean exit on failed startup
- CI: `container` job in `model-regression.yml`

**Verified locally:** build PASS; size gate PASS; container tests 16/16 (real `/predict`, `--network none --read-only`, health, SIGTERM, missing/corrupt/wrong-checksum weights); EAP-2 29/29; repository 507 passed / 2 inherited CPU1 failures; org lint gate 0 findings.

**Not verified:** GitHub Actions run (Actions is not running on this repo); physical network disconnection.

Evidence: `reports/eap3/EAP_3_Production_Review.md`, `reports/eap3/eap3_summary.json`.
