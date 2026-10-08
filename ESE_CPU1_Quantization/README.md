# ESE-CPU1: CPU deployment quantization

This task exports the existing12-class CME-OPT2 detector as ONNX FP16 and
OpenVINO INT8. Source weights, trained-model registry entries, confidence policy,
ByteTRACK and production Backend defaults are preserved. There is no retraining.
Deployment versions reference the existing source version rather than implying
another training run. The measured report is at
[`../SED_3_Stress_Testing/reports/ESE_CPU1_Quantization_Report.md`](../SED_3_Stress_Testing/reports/ESE_CPU1_Quantization_Report.md).

## Environment

Use Python3.12 in an isolated virtual environment. The task environment may
reuse installed CPU PyTorch through `--system-site-packages`; task packages
remain installed inside the venv. A clean machine can install CPU wheels first:

```powershell
py -3.12 -m venv ESE_CPU1_Quantization/runtime/venv
ESE_CPU1_Quantization/runtime/venv/Scripts/python.exe -m pip install torch==2.10.0 torchvision==0.25.0 --index-url https://download.pytorch.org/whl/cpu
ESE_CPU1_Quantization/runtime/venv/Scripts/python.exe -m pip install -r ESE_CPU1_Quantization/requirements.txt
```

Ultralytics8.4.24 uses `int8=True`/`half=True`; `quantize=8/16` is unsupported
in this pinned version. Its CPU ONNX exporter cannot directly export half,
so the pipeline exports FP32 ONNX then uses onnxconverter-common FP16 conversion
with FP32 IO. The stored graph contains FP16 weights. CPU execution providers
may promote unsupported FP16 kernels; no native CPU FP16 arithmetic is claimed.

## Reproduce

```powershell
ESE_CPU1_Quantization/runtime/venv/Scripts/python.exe Backend/scripts/export_quantized_models.py --weights Backend/best.pt --data Hazard_Expansion/configs/12class_data.yaml --calibration-images 300 --imgsz 640 --output-root Backend/weights
ESE_CPU1_Quantization/runtime/venv/Scripts/python.exe -m ESE_CPU1_Quantization.select_ptq
ESE_CPU1_Quantization/runtime/venv/Scripts/python.exe -m ESE_CPU1_Quantization.profile_cpu
ESE_CPU1_Quantization/runtime/venv/Scripts/python.exe SED_3_Stress_Testing/scripts/benchmark_quantization.py --weights Backend/best.pt --output SED_3_Stress_Testing/reports/quant_report.json
ESE_CPU1_Quantization/runtime/venv/Scripts/python.exe -m unittest discover -s ESE_CPU1_Quantization/tests -v
python Experiment_Tracking/scripts/validate_registry.py
```

Exports are `Backend/weights/onnx_fp16/best_fp16.onnx` and
`Backend/weights/openvino_int8/{model.xml,model.bin,metadata.yaml}`.
The exporter refuses to overwrite an existing selected IR. Move an earlier
version to a distinct archive before reproducing. The exact300-path training
manifest uses coverage-aware seeded selection and excludes byte-identical
held-out images. Calibration YAML is generated in ignored runtime storage;
the existing dataset bytes/splits remain intact. Validation selects PTQ;
all formats use identical held-out test evaluation settings.

Standard NNCF PTQ runs first, using the unmodified Ultralytics detection-head
ignored scope and MIXED preset. If validation mAP@50 degradation is at least
0.8percentage points, `select_ptq` invokes NNCF accuracy control with an absolute
0.0079 maximum drop on the0–1 metric scale. Validation data guides restoration;
test data never calibrates or selects PTQ. Attempts and selection are recorded.

The measured basic test result missed the strict target even though validation
passed. The actual recovery used `select_ptq --resume-baseline
--force-accuracy-aware`, retaining the first benchmark as
`reports/basic_ptq_quant_report.json`. The resulting candidate was selected on
validation; its held-out test loss was worse. Both attempts remain visible.
Reproducing that investigation requires the explicit force option after the
first benchmark. No source training or test-based parameter search follows it.

The official benchmark uses CPU only, batch1, static640×640,30 warmups and200
timed observations per format and latency category. Model timing starts with
preprocessed tensors; end-to-end includes in-memory image decode, preprocessing,
inference and NMS. It excludes disk IO and downstream tracking/alerts. Raw samples
and mean/P50/P90/P95/P99/min/max remain visible. OpenVINO uses LATENCY hint,
one stream. A preliminary1/2/4-thread profile selects a documented setting
before the official200-call benchmark; all three formats use that thread count.
ORT uses CPUExecutionProvider and one inter-op thread. Compilation and startup
are outside steady-state timing; preliminary and official results stay separate.

The primary size gate counts XML+BIN using decimal MB (<6,500,000bytes), with
runtime metadata reported separately. Accuracy gates are strictly <0.8pp and
<1.0pp. Performance is hardware-specific; unit tests do not assert20ms on every
machine. The required measured accuracy test reads actual benchmark results
and errors if the evidence is missing.

## Offline Git delivery

The required branch is `feature/atlantis-openvino-quant`, based on the completed
CME-OPT3 branch. This task contributes exactly two commits; previous tasks remain
in its ancestry. Repository access was revoked, so push and PR creation are
deferred. The local commits require no GitHub access and keep their hashes when
pushed later. When access returns, run from the repository:

```powershell
git push -u origin feature/atlantis-openvino-quant
```

Alternatively run `sync_when_access_returns.ps1`. It performs a normal push,
sets upstream tracking, and never rewrites remote history. If the organization
changes the repository URL again, update `origin` to the actual restored URL.
Do not force-push to bypass permission or history errors.

A verified full Git bundle is saved in ignored `backups/`, together with an
archive of deployment binaries and their hashes. Git intentionally excludes
videos, datasets, checkpoints, deployment binaries and local caches. The bundle
preserves the commits; the deployment archive separately preserves generated
models. Keep a copy of both backups outside this workspace for disk-loss recovery.
To recover into another directory, use `git clone <bundle-path> <new-directory>`,
then configure its `origin` to the organization's restored repository.
