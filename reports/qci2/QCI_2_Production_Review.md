# QCI-2 — Defect classifier and anomaly/attention heatmap review

**Real training, held-out evaluation and model attribution completed. Local
technical gates PASS; QCI-2 OVERALL FAIL for full repository/PR/release readiness.**
Organization access is revoked. Two existing CPU1 quantitative tests remain
unmet. Dataset permits noncommercial research/review, not unlicensed commercial
deployment. No numeric accuracy or latency threshold was supplied for QCI-2.

## Objective, Git and QCI-1 dependency

Train a genuine local surface classifier and explain predictions from the model.
Branch `feature/sprint2-qci2-defect-classifier`, created from QCI-1 HEAD
`d63ff417b363ea8fd81e0027f9ca458afdda4aee`. This branch isolates the next task while
preserving all earlier work. Implementation sits in a separate task folder inside
IndusriX, integrated by `Training/train_qci2_classifier.py`; no separate project,
new dataset ingestion or segmentation model is introduced. QCI-1 files unchanged.

Actual QCI-1 successful manifest: `reports/qci1/segmentation/dataset_manifest.json`.
Version `QCI1-local-segmentation-v1`, SHA256 `08921a7c0713103220e9c0aec3d6987c5737c1fcf8c81c8895251b2ae94586bb`.
Records SHA256 `6801e212b235541cb46988f499983676fa0a1123b9dc08d12d7581e754e77d8f`. The original seven-class textile
corpus has only boxes and remains BLOCKED for segmentation; it is not silently
substituted. QCI-2 consumes the validated366-pair curated KolektorSDD fine masks.
All original quarantines, source class map and physical-item splits are preserved.

| Split | Normal | Defect | Total |
| --- | --- | --- | --- |
| Train |263|39|302|
| Validation |42|6|48|
| Test |14|2|16|

Source segmentation class0:defect becomes classifier class1:defect; classifier
class0:normal comes from **verified empty foreground masks**. This documented
mask-presence rule is binary image-level classification, not guessed multiclass
or multi-label semantics. Masks never enter classifier inputs or heatmap generation.
Full images are used; no ground-truth crop gives the classifier defect location.
No test split reshuffle, optimization, threshold tuning or model selection.

Dataset [publisher/license](https://www.vicos.si/resources/kolektorsdd/):
CC BY-NC-SA4.0. Commercial permission has not been obtained. Cite Tabernik et al.,
*Segmentation-Based Deep-Learning Approach for Surface-Defect Detection*,
DOI10.1007/s10845-019-01476-x. Evidence is for local noncommercial research/review.

## Model architecture and local assets

[ResNet18](https://docs.pytorch.org/vision/stable/models/generated/torchvision.models.resnet18.html),
two-class head, **11,177,538 parameters**, **4,721,666
trainable**. Actual existing cached ImageNet checkpoint:
`C:/Users/ehtis/.cache/torch/hub/checkpoints/resnet18-f37072fd.pth`;
SHA256 `f37072fd47e89c5e827621c5baffa7500819f7896bbacec160b1a16c560e07ec`. A portable verified copy is in
`QCI_2_Defect_Classifier/runtime/initialization/`. No download occurred.
Build uses `weights=None`, then explicit local `torch.load(weights_only=True)`.
Fine-tune final residual block and linear head only; freeze all BatchNorm running
statistics. This cached moderate model fits the local2-core/4-logical CPU rather
than selecting a huge architecture. PyTorch2.10.0+cpu/Torchvision0.25.0; no GPU used.

Input **448x192 RGB**: QCI-1 aspect-preserving letterbox,
no center crop, area shrink/linear enlarge, padding114, CHW float32/255 with
ImageNet mean/std. Train-only horizontal flips probability0.5
and mild brightness/contrast±0.08; label presence is
invariant and no mask crop is consumed. Validation/test are deterministic.

## Training configuration and real results

Seed42; deterministic PyTorch algorithms; CPU threads2;
batch8; workers0/no worker prefetch/pinning; AdamW
last-block lr0.0001, head lr0.001,
weight decay0.0001; cosine schedule over40
requested epochs; early stopping patience8. Inverse train-frequency
cross-entropy weights **[0.5741444826126099, 3.8717949390411377]**, calculated only from263/39.
No artificial balancing or normal-class invention.

Epochs requested **40**, completed **31**,
best **23**. Validation macro F1 selects the model; ties
use lower weighted validation loss. Best validation metrics:
`{'samples': 48, 'accuracy': 1.0, 'macro_precision': 1.0, 'macro_recall': 1.0, 'macro_f1': 1.0, 'confusion_matrix': [[42, 0], [0, 6]], 'per_class': [{'class_id': 0, 'class_name': 'normal', 'support': 42, 'precision': 1.0, 'recall': 1.0, 'f1': 1.0}, {'class_id': 1, 'class_name': 'defect', 'support': 6, 'precision': 1.0, 'recall': 1.0, 'f1': 1.0}]}`; weighted loss0.00350806.
Real duration1976.805s. Mini-batch smoke forward/backward
was finite and took no optimizer step. Best/last checkpoint and config/history
saved without overwriting earlier runs. Selected checkpoint reloaded and validation
metrics reproduced. Training RSS is separately logged as observed per-batch values;
those observations are not claimed as a continuously sampled peak/stability test.

Model version `qci2-kolektor-resnet18-v1`. Selected weights `QCI_2_Defect_Classifier/runtime/run_v1/best.pt`,
SHA256 **`00f626cf837139c3476dd4f2c77b4b0a8faa7e4b368af13936b33ddca838b795`**. Training-base commit `d63ff417b363ea8fd81e0027f9ca458afdda4aee`;
the exact executed source snapshots match hashes recorded before training under
`runtime/execution_sources/`. Later committed code adds path/contract hardening,
reports, tracking and recovery; the registry records that implementation commit
separately. No false claim that uncommitted training had a future commit hash.

## Final held-out test evaluation and failure analysis

Selected checkpoint evaluated once, after validation-only selection. All16 test
images and all predictions are reported; tiny test support, particularly **two
defective images**, limits generalization and statistical conclusions.

- Accuracy **1.000000**.
- Macro precision **1.000000**.
- Macro recall **1.000000**.
- Macro F1 **1.000000**.

| ID | Class | Support | Precision | Recall | F1 |
| --- | --- | --- | --- | --- | --- |
| 0 | normal | 14 | 1.000000 | 1.000000 | 1.000000 |
| 1 | defect | 2 | 1.000000 | 1.000000 | 1.000000 |

Confusion matrix (actual rows, predicted columns, normal/defect order):
`[[14, 0], [0, 2]]`. Raw metrics, per-image scores, complete
misclassification list, confusion matrix plot and all-test visualization retained.

No test misclassifications were observed. Every test image is included, rather than inventing failure examples.

The test metrics do not satisfy an invented threshold. Zero observed errors on
a small split would not prove production accuracy or factory-domain robustness.

## Genuine model-attribution heatmaps

[Grad-CAM](https://arxiv.org/abs/1610.02391) targets the inspected actual final
convolution `layer4.1.conv2`. Spatial mean gradients of the selected class logit
weight actual forward activations, followed by ReLU and finite normalization.
Default target=predicted class; explicit0/1 debugging target supported. Ground-truth
mask is a separate reference column, never passed as the explanation.
Maps invert exact letterbox geometry to source image dimensions. Raw normalized
PNG and TURBO overlay saved separately, alpha up to0.35 scaled by heatmap strength.
Degenerate maps stay zero with warnings, not synthetic Gaussian overlays.

Generated **16** actual test explanations; finite
image-aligned **16**, degenerate
**0**. Every held-out test sample appears in
`classifier_heatmap_sanity_grid.png`, including mistakes/low-confidence cases
when present. Tiny fixtures only test code, not production model quality.
Optional pointing/inside-mask energy probes appear for positive test images;
they are descriptive, not causality or interpretability-accuracy guarantees.
Coarse14x6 feature attribution cannot replace thin pixel defect segmentation.

## Inference, errors, latency and memory

Reusable `DefectClassifier.predict()` returns Pydantic v2 confidence/class scores,
target-specific heatmap metadata, model version and actual classifier/CAM/combined
latencies. Failures return no invented class, confidence, heatmap path or version.
Missing/corrupt image/model, checksum/class-map/config mismatch, invalid target,
unsupported type and attribution failures are controlled. Low confidence is
reported; softmax is uncalibrated. Requests serialize on one model lock.
Classification uses eval/inference mode; only the attribution pass enables
gradients. Scoped hook is always removed, captured activations cleared and model
gradients cleared; no retained historical tensors, graphs or hook accumulation.

Bounded adapter metadata max10,000 records and bounded line/manifest sizes;
never preload images. CPU workers0 retains only current batch. Source image and
mask hashes match QCI-1; split IDs and label contract are checked. Input pixels,
config batch and artifact bytes have explicit ceilings. Saved explanations are
only requested current artifacts, not an unbounded memory cache.

Dedicated production workload:20 warm calls, then **480**
real classifier+Grad-CAM calls in two matched240-call windows, complete identical
48-image validation mixes repeated five times each. No disk-map export in latency
profile; combined time includes decode/preprocessing/prediction/CAM alignment.

| Timing | Mean ms | P95 ms |
| --- | --- | --- |
| Classifier forward |117.459|169.990|
| Separate attribution pass/alignment |129.748|189.498|
| Complete request |272.067|412.961|

RSS start **382.250MiB**, peak **393.812MiB**,
end **382.230MiB**. Stable window means
**382.066 -> 382.332MiB**.
Drift **0.069702%**, strict<5% **True**.
Metric=absolute full-window mean difference/first mean after warm-up; raw endpoints
retained separately. Peak sampled20Hz, 2372 observations.
No retained parameter gradients/hooks after any request. Finite benchmark is not
proof of zero possible future leaks. No supplied numeric latency SLA;500ms template
was not silently adopted as an acceptance requirement.

## Offline verification, tests and proof

Actual train, final evaluation, inference and CAM profiling ran with Python TCP
connect/connect_ex blocked: attempted external connections0, runtime downloads0,
cloud model/storage/annotation APIs0. All model definitions/weights/images/fonts
are local. Physical WiFi was not disconnected. Separate local MLflow tracking uses
the existing loopback-IPC-safe guard and file:// store. No GPU/Modal session or
idle GPU billing; CPU run needs no GPU shutdown action.

QCI-2: collected32, **32 passed**, 0 failed,
0 skipped,0 errors, 14.09s.
QCI-1 regression: **74 passed**, 0 failed,
8.70s. Normal full-root `pytest -q`: collected
281, **279 passed**, **2 failed**,
0 skipped,0 errors,88.49s.
The remaining two old CPU1 numeric failures are artifact11.773MB vs6.5MB and AP50
drop1.025pp vs<1pp. Their thresholds/tests were not changed or hidden.
Compile/import checks pass; no unrelated lint infrastructure introduced.

Proof is raw captured pytest/train/evaluation/profile terminal output, real
confusion/training plots, all-test attribution grid, structured JSON and actual
fresh headless Edge capture of the local evidence page. No fake OS-terminal or
fixture-as-production screenshot. Existing CSV/local MLflow record model version,
dataset hashes, source commit, actual hyperparameters/metrics and artifact SHA.
No fabricated detection mAP for a classifier.

## Delivery, known limitations and DoD

Exactly two local QCI-2 commits, author `ehtisham5618 <ehtisham.malik5618@gmail.com>`.
Complete-history Git bundle and independently hashed dataset/model/runtime ZIP
are in ignored task `backups/`; fresh-clone restore verifies real predictions
and CAM using recovered files, not original absolute data paths. Future sync
script is verified against a disposable local bare repository. No GitHub push,
PR/URL, merge/release or Slack submission claimed while access is revoked.

Later sync: `powershell -ExecutionPolicy Bypass -File QCI_2_Defect_Classifier/sync_when_access_returns.ps1`.
Limits: tiny noncommercial single-source binary dataset, sparse held-out positive
support, coarse attribution and uncalibrated scores. Model is not a seven-class
textile/hazard detector and is not declared factory-production validated.

| Gate | Result |
| --- | --- |
| Required feature branch | PASS |
| QCI-1 validated data consumed | PASS |
| Actual target and binary design justified | PASS |
| Verified local starting assets | PASS |
| No runtime cloud API dependency | PASS |
| Pydantic v2 contracts | PASS |
| Typed/documented new functions | PASS |
| Bounded loaders | PASS |
| Deterministic training settings | PASS |
| Train class imbalance handled | PASS |
| Real classifier training completed | PASS |
| Best saved/reloaded | PASS |
| Once-only held-out test evaluated | PASS |
| Per-class metrics/confusion matrix | PASS |
| Real model-gradient heatmaps | PASS |
| Heatmap sanity tests | PASS |
| Typed inference JSON | PASS |
| Malformed inputs controlled | PASS |
| Offline model/heatmap verified | PASS |
| Production inference RSS measured | PASS |
| Stable drift strict<5% | PASS |
| QCI-2 tests100% passing | PASS |
| QCI-1 regression | PASS |
| Entire repository tests | FAIL; prior CPU1 numeric gates |
| Docs and actual visual/terminal proof | PASS |
| PR created | FAIL; organization access revoked |
| Commercial dataset permission | NOT OBTAINED; noncommercial research only |
| QCI-2 OVERALL | FAIL; local technical work complete, full repository/PR/release gates pending |

Changed: task package/config/README, thin existing Training entry, root QCI-2 tests,
minimal root README/requirements/.gitignore, existing experiment registry support
and appended model/run rows, measured reports/proof. QCI-1 source/data/splits and
existing model/tracker/UI work unchanged. Dataset binaries, weights, venvs,
credentials and runtime/recovery ZIPs excluded from Git.

## Verified tracking

Existing local MLflow run `51d850115d9c4dfab76c6cbd05cb39d3`; committed implementation `00c986732afd2ea8dbced39b015aa63d12408c04`. Registry validation:23 experiments,8 model versions,4 alert policies, PASS. One historical CME1 missing-mAP warning remains; no classifier mAP was invented.

## Recovery launcher hardening

Two initial full-launcher restore checks hit a controlled native OpenCV error. Clean standalone restored-model checks passed; an isolated PATH comparison passed with both environments, so DLL-path mutation alone is not established as the cause. The packaging parent now uses only the Python standard library, reducing memory pressure and avoiding native-library environment side effects before spawning model verification. Initial failure evidence is retained in recovery_native_environment.json and the ignored backup logs. Final recovery must pass before delivery.
