# syntax=docker/dockerfile:1.7
# IndustriX CPU inference service (EAP-3). Multi-stage: build a venv, ship only
# the venv + runtime source. Targets:
#   runtime  - no weights; mount the verified checkpoint at /models/best.pt
#   bundled  - (default) self-contained offline gateway image with best.pt and
#              the ESE-CPU1 OpenVINO INT8 artifact baked in
# Size gate: unpacked image filesystem < 1.8 GB (decimal, 1 800 000 000 bytes); see EAP_3_Lightweight_Docker.

ARG PYTHON_IMAGE=python:3.12.12-slim-bookworm

FROM ${PYTHON_IMAGE} AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY EAP_3_Lightweight_Docker/requirements-runtime.txt /tmp/requirements-runtime.txt
# Ultralytics alone is installed --no-deps so its GUI opencv-python requirement is
# satisfied by opencv-python-headless (pinned in the requirements file).
RUN grep -v '^ultralytics==' /tmp/requirements-runtime.txt > /tmp/requirements-deps.txt \
 && pip install --no-compile -r /tmp/requirements-deps.txt \
 && pip install --no-compile --no-deps "$(grep '^ultralytics==' /tmp/requirements-runtime.txt)" \
 && find /opt/venv -depth -type d -name '__pycache__' -exec rm -rf {} + \
 && python -c "import torch, torchvision, cv2, ultralytics, openvino, fastapi, reportlab; import importlib.util as u; assert u.find_spec('polars') is None; print('deps ok', torch.__version__, ultralytics.__version__)"

FROM ${PYTHON_IMAGE} AS runtime
# libgomp1: OpenMP runtime for PyTorch/OpenCV CPU kernels. No compilers ship here.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 10001 industrix \
 && useradd --system --uid 10001 --gid industrix --home-dir /app --shell /usr/sbin/nologin industrix
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
# Runtime import closure of Backend/main.py (traced in EAP-3); tests, notebooks,
# runtime state and datasets are excluded by .dockerignore.
# Backend code/config only: checkpoints and exported weights belong to the bundled target.
COPY Backend/*.py Backend/
COPY Backend/configs/ Backend/configs/
COPY Backend/incidents/ Backend/incidents/
COPY CME_OPT3_ByteTrack/ CME_OPT3_ByteTrack/
COPY Confidence_Calibration/ Confidence_Calibration/
COPY ESE_CPU1_Quantization/ ESE_CPU1_Quantization/
COPY ESE_CPU3_Soak_Test/ ESE_CPU3_Soak_Test/
COPY QCI_1_Surface_Defect_Segmentation/ QCI_1_Surface_Defect_Segmentation/
COPY QCI_2_Defect_Classifier/ QCI_2_Defect_Classifier/
COPY QCI_3_Severity_IoT/ QCI_3_Severity_IoT/
COPY QCI_4_Edge_Telemetry/ QCI_4_Edge_Telemetry/
COPY QCI_5_Incident_PDF/ QCI_5_Incident_PDF/
COPY SED_1_Multi_Camera/ SED_1_Multi_Camera/
COPY SED_2_Alert_Escalation/ SED_2_Alert_Escalation/
COPY SED_3_Stress_Testing/ SED_3_Stress_Testing/
# Incidents, QCI-3 and QCI-4 share Backend/data/events.db by design; point it at the
# /data volume so the root filesystem can stay read-only.
RUN mkdir -p /models /data/snapshots /app/SED_2_Alert_Escalation/runtime \
 && ln -s /data /app/Backend/data \
 && chown -R industrix:industrix /data /app/SED_2_Alert_Escalation/runtime
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    YOLO_OFFLINE=true \
    YOLO_AUTOINSTALL=false \
    YOLO_CONFIG_DIR=/tmp \
    MPLCONFIGDIR=/tmp/matplotlib \
    INDUSTRIX_MODEL_PATH=/models/best.pt \
    INDUSTRIX_REQUIRE_MODEL=1 \
    INCIDENT_DATABASE=/data/events.db \
    INCIDENT_SNAPSHOTS=/data/snapshots \
    INFERENCE_ENGINE=pytorch
USER industrix
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD ["python", "-c", "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=8).status == 200 else 1)"]
STOPSIGNAL SIGTERM
CMD ["uvicorn", "Backend.main:api_app", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "30"]

FROM runtime AS bundled
COPY Backend/best.pt /models/best.pt
COPY Backend/weights/openvino_int8/ /app/Backend/weights/openvino_int8/
ENV INDUSTRIX_MODEL_SHA256=c4aba081f6357e23a7370a5f7cf98eff2c6faa0c4c20a2d4dcb8bcabdd490061
