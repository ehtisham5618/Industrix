# EAP-3 — Lightweight Multi-Stage Dockerfile

CPU container for the IndustriX FastAPI inference service (`Backend/main.py`,
`uvicorn Backend.main:api_app`, port 8000). Files: `Dockerfile`, `.dockerignore`,
`compose.yaml`, `EAP_3_Lightweight_Docker/` (runtime requirements, size gate, tests).
Measured results and evidence: `reports/eap3/`.

## Stages
| Stage | Base | Contents |
|---|---|---|
| `builder` | `python:3.12.12-slim-bookworm` + build-essential | `/opt/venv` from `requirements-runtime.txt` |
| `runtime` | same slim base + `libgomp1` | venv, the service's traced import closure, non-root user `industrix` (10001); **no weights** |
| `bundled` (default) | `runtime` | + `best.pt` (`/models/best.pt`, SHA256 `c4aba081…0061`) + ESE-CPU1 OpenVINO INT8 |

Python 3.12 matches the environment where the full repository suite passes.
Compilers stay in the builder; the runtime image has no gcc/cc/make (tested).

## Dependencies
`EAP_3_Lightweight_Docker/requirements-runtime.txt` is the runtime subset of
`requirements.txt`, pinned to tested versions. Differences, each deliberate:
- **CPU-only torch/torchvision** (`+cpu` wheels): the default Linux wheels carry several GB of CUDA libraries the CPU gateway never uses.
- **`opencv-python-headless`** instead of `opencv-python`: no X11/GUI libraries; ultralytics is installed `--no-deps` so the GUI build is never pulled in.
- **polars omitted** (~216 MB): ultralytics 8.4.24 imports it lazily only for training, benchmarks, plots, W&B and DataFrame exports; serving never imports it. The builder asserts it is absent; container tests exercise real inference without it.
- Notebook, Kaggle, Albumentations, MLflow and test tooling are excluded.
Update this file whenever `requirements.txt` changes a runtime package.

## Build and measure
```powershell
docker build -t industrix:eap3 .                              # bundled (needs Backend/best.pt locally)
docker build --target runtime -t industrix:eap3-runtime .     # no weights
python EAP_3_Lightweight_Docker/check_image_size.py industrix:eap3 --compressed --out reports/eap3/image_size_bundled.json
```
**Size gate:** unpacked image filesystem < 1 800 000 000 bytes (decimal 1.8 GB,
stricter than 1.8 GiB), measured as `du -sxb /` in a fresh `--network none`
container. `docker image inspect .Size` is recorded but not used: on Docker
Desktop's containerd image store it reports *compressed* content, and
`docker image ls` "disk usage" adds compressed blobs to unpacked snapshots.

## Run
```powershell
docker run -d --name industrix -p 127.0.0.1:8000:8000 -v industrix-data:/data --read-only --tmpfs /tmp industrix:eap3
curl http://127.0.0.1:8000/health
# Weightless image with a mounted, checksum-verified checkpoint:
docker run -d -p 127.0.0.1:8000:8000 -v ${PWD}/Backend/best.pt:/models/best.pt:ro `
  -e INDUSTRIX_MODEL_SHA256=c4aba081f6357e23a7370a5f7cf98eff2c6faa0c4c20a2d4dcb8bcabdd490061 industrix:eap3-runtime
docker compose up -d                       # bundled; `--profile mounted` for the mounted variant
```

| Variable | Default (image) | Meaning |
|---|---|---|
| `INDUSTRIX_MODEL_PATH` | `/models/best.pt` | Checkpoint; an explicit path never falls back to another file |
| `INDUSTRIX_REQUIRE_MODEL` | `1` | Startup fails (container exits) if the model is missing or unloadable |
| `INDUSTRIX_MODEL_SHA256` | set in `bundled` | Startup fails on checksum mismatch |
| `INFERENCE_ENGINE` | `pytorch` | `openvino` selects the ESE-CPU1 INT8 stream engine |
| `INCIDENT_DATABASE` / `INCIDENT_SNAPSHOTS` | `/data/...` | Writable incident storage (mount a volume) |

Writable paths: `/data` (volume), `/tmp` (tmpfs), `/app/SED_2_Alert_Escalation/runtime`.
Everything else can be read-only (`--read-only` is tested).

## Offline
`YOLO_OFFLINE=true`, `YOLO_AUTOINSTALL=false`, and `Backend/offline_policy.py`
(declines OpenVINO telemetry) are set in the image. The container test suite
runs real inference with `--network none --read-only`.

## Health and shutdown
`GET /health` returns 200 with the model path, SHA256 and class count only when the
detector is loaded (503 otherwise); the image's `HEALTHCHECK` calls it with Python
(no curl in the image). Uvicorn is PID 1 in exec form, so SIGTERM triggers a
graceful shutdown (30 s timeout; tested to exit 0).

## Tests
```powershell
python -m pytest EAP_3_Lightweight_Docker/tests -v -rs      # needs Docker + both images for container checks
```
Static checks run anywhere; container checks skip with a reason when Docker or the
images are absent (`EAP3_REQUIRE_DOCKER=1` turns that into a failure).

## Known limitations
- Camera video files for `/streams/start` are not in the image; mount them at the paths in `CAMERA_CONFIG`.
- The QCI-2 classifier weights (CC BY-NC-SA, local only) are not bundled.
- `/predict` still loads the whole upload into memory (unchanged behaviour); put a request-size limit in the reverse proxy.
- CI builds the weightless target only; the bundled image's real-inference tests run where `Backend/best.pt` exists.
