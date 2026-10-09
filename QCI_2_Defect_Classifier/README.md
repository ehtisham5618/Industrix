# QCI-2 — Defect classifier training and model-attribution heatmaps

This task lives in a separate folder within IndusriX and consumes QCI-1; it does
not ingest a new dataset, alter QCI-1 files or train a segmentation model.
`Training/train_qci2_classifier.py` plugs into the existing Training directory.
`DefectClassifier.predict()` is the reusable typed inference service.

The actual successful QCI-1 dataset is the curated KolektorSDD fine-mask corpus:
302 train (263 normal/39 defect),48 validation (42/6),16 test (14/2). A verified
empty indexed mask means normal; a positive canonical defect mask means defect.
Classification IDs are `0:normal,1:defect`; QCI-1 segmentation ID0:defect maps
to classifier ID1. The seven-class original textile source is box-only BLOCKED
and is not silently substituted. Multi-label classification is unnecessary for
this binary mask-presence task. All physical-item groups and splits are unchanged.

Dataset license: CC BY-NC-SA4.0, local noncommercial research/review only.
Commercial deployment requires publisher permission. Source/citation:
[ViCoS KolektorSDD](https://www.vicos.si/resources/kolektorsdd/), Tabernik et al.,
DOI10.1007/s10845-019-01476-x. Classifier checkpoints inherit these data-use limits.

## Local execution

Use the existing backend Python3.12.9 environment. PyTorch2.10.0 CPU,
Torchvision0.25.0 and Pydantic2.12.5 were installed before this task; no new
package/model download was used. Run from the repository root:

```powershell
$taskPython = '.\ESE_CPU1_Quantization\runtime\venv\Scripts\python.exe'
& $taskPython Training/train_qci2_classifier.py --config QCI_2_Defect_Classifier/configs/qci2_classifier.yaml
& $taskPython -m QCI_2_Defect_Classifier.infer --image QCI_1_Surface_Defect_Segmentation/runtime/segmentation_dataset/images/test/kos18/Part0.jpg --json QCI_2_Defect_Classifier/runtime/prediction.json
& $taskPython -m QCI_2_Defect_Classifier.run_checks
```

The example image path is an existing QCI-1 sample, not an invented fixture.
Default trained checkpoint: `QCI_2_Defect_Classifier/runtime/run_v1/best.pt`.
Training preserves an existing run directory instead of overwriting it. For an
independent reproduction, use `configs/qci2_reproduce.yaml`: same settings and
checkpoint SHA, a portable local initialization copy, explicit restored QCI-1
dataset-root override and fresh `runtime/reproduction_run/` output.
The override verifies the original source metadata hash and preserves manifest
bytes, label identities and splits; no QCI-1 ingestion is repeated.

Training and inference run with Python TCP connect/connect_ex blocked. No
torchvision pretrained enums, remote checkpoint URI, runtime installs, cloud
annotation/model APIs or external model definitions are used. All weights/data
are explicit local files. No GPU/Modal connection was started for this CPU task.

## Model and reproducibility

ResNet18 uses the actual local ImageNet checkpoint already cached at
`C:/Users/ehtis/.cache/torch/hub/checkpoints/resnet18-f37072fd.pth`, SHA256
`f37072fd47e89c5e827621c5baffa7500819f7896bbacec160b1a16c560e07ec`.
`resnet18(weights=None)` is built first; the local state dictionary is loaded
with `weights_only=True`. The replaced two-class head gives11,177,538 parameters.
Only final residual block and head are trainable:4,721,666 parameters. Every
BatchNorm running statistic remains frozen. This moderate cached backbone fits
the two-core local CPU and avoids downloading a larger architecture.

Full-image448x192 letterboxing reuses QCI-1 geometry and preserves the whole
surface instead of a center crop that might cut out defects. RGB CHW float32/255
uses ImageNet mean/std. No masks/ground-truth crops are passed to the classifier.
Train-only horizontal mirroring and mild±8% brightness/contrast preserve
image-level mask presence. No validation/test augmentation.

Explicit config: seed42, CPU threads2, batch8, workers0/no prefetch/pinning,
AdamW, final-block lr0.0001/head lr0.001, weight decay0.0001, cosine schedule40
requested epochs, validation early-stop patience8. Inverse training frequencies
give cross-entropy weights0.57414448 normal/3.87179494 defect. Macro F1 selects
the best epoch; equal F1 uses lower weighted validation loss. Test data is not
used for optimization, checkpoint selection or threshold tuning.

Python/NumPy/PyTorch seeds and deterministic algorithms are enabled. Source,
records, initialization and selected artifact hashes provide lineage; exact
executed training files are preserved in ignored `runtime/execution_sources/`,
matching their hashes recorded before the run. Reports distinguish training-base
commit from the later committed implementation/tracking commit. A mandatory
real-batch forward/backward smoke check does not take an optimizer step.

Run `evaluate` once after training. It refuses to overwrite final test metrics.
It evaluates all16 untouched test images and visualizes all predictions, rather
than cherry-picking successes. Sparse two-positive test support limits claims.
No numeric classifier accuracy or latency SLA was supplied; actual measurements
are reported without inventing an acceptance threshold.

## Attribution and typed errors

Grad-CAM targets the inspected final convolution `layer4.1.conv2`. Spatial mean
gradients of the actual selected class logit weight its feature maps, followed
by ReLU and finite0..1 normalization. A scoped forward hook is removed in
`finally`; no backward hooks, graph cache or parameter gradients are retained.
Requests serialize on one model lock. Classification uses inference mode;
only the separate attribution pass enables gradients. Degenerate maps stay
zero with an explicit warning rather than synthetic saliency.

Attribution is resized through the exact inverse letterbox to original image
dimensions. Raw normalized PNG and TURBO overlay are separate artifacts, alpha
up to0.35 scaled by activation strength. Default target is predicted class;
`--target-class 0` or `1` supports explicit debugging. Ground-truth masks appear
in their own grid column and are never substituted for model output.
Coarse Grad-CAM is an attribution aid, not a segmentation prediction, calibrated
anomaly probability, causal proof or guaranteed defect localization.

Pydantic v2 contracts reject unknown fields, invalid IDs/configs, URL/UNC input
and nonfinite outputs. Missing/corrupt image/model, bad class map/hash, unsupported
type and attribution failures return FAILED with no invented confidence/class/
heatmap/model version. Low softmax confidence is reported; scores are uncalibrated.
Inference CLI returns0 on SUCCESS and1 on controlled failure.

## Memory, evidence and tracking

The adapter stores bounded metadata (at most10,000 typed rows), never image
tensors. Images/masks are hash-checked against QCI-1. Loader workers0 produces
only the current batch, with no asynchronous prefetch queue. Single-image
Grad-CAM keeps only current buffers; files persist only when explicitly requested.

`profile_inference` warms20 calls, then measures two matching full validation
cycles (five repeats of48 images each). Stability is the absolute difference
of mean RSS per240-call window divided by first mean, strict<5%. Transient peak
is sampled20Hz. Raw endpoints and latency mean/P95 are recorded separately.
This finite benchmark does not prove absence of all possible future leaks.

`reports/qci2/` stores training/history, model checksum metadata, once-only test
metrics/predictions/confusion matrix, real all-test heatmap grid and overlays,
memory/latency CSV/JSON, terminal pytest proof and production review. Existing
CSV registries and local MLflow record actual classifier lineage and metrics;
detection mAP is not fabricated for classification. Full-root prior CPU1
quantitative failures remain visible, with unchanged thresholds.

## Two-commit offline delivery

Branch `feature/sprint2-qci2-defect-classifier` starts at QCI-1 HEAD
`d63ff417b363ea8fd81e0027f9ca458afdda4aee`. Exactly two task commits preserve
implementation and measured evidence, author `ehtisham5618` with
`ehtisham.malik5618@gmail.com`. Repository access is revoked, so PR/push are pending.
No merge, release or Slack submission is claimed. `pr_description.md` and EOD
update are ready to paste.

After the two commits, `offline_backup` verifies a complete-history Git bundle,
every runtime archive member hash, recovered actual model+Grad-CAM in a fresh
clone and the sync helper against a disposable LOCAL bare repository. Backups
contain real QCI-1 curated data/metadata, trained best/last weights, initialization
copy, exact executed source files and local tracking. Venvs/secrets are excluded.

Restore `QCI_2_complete_history.bundle` into a fresh folder, then extract
`QCI_2_local_model_and_runtime.zip` there. Restore origin to
`https://github.com/devlogixtechnology/industirx.git`; run the inference CLI with
an extracted sample. The original absolute training paths are provenance;
portable reproduction config supplies explicit restored dataset/weights paths.
Once access returns, run:

```powershell
powershell -ExecutionPolicy Bypass -File QCI_2_Defect_Classifier/sync_when_access_returns.ps1
```

Normal named-branch push only; no force push or rewriting earlier tasks.
