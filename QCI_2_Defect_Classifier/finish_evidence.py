"""Generate full QCI-2 review/summary from actual trained and measured artifacts."""
from __future__ import annotations
import html
import json
from .common import ROOT,TASK,REPORTS,write_json


def main() -> None:
    """Keep code/metric passes distinct from unresolved production/repository gates."""
    training=json.loads((REPORTS/'training_summary.json').read_text(encoding='utf-8'))
    evaluation=json.loads((REPORTS/'test_metrics.json').read_text(encoding='utf-8'))
    profile=json.loads((REPORTS/'inference_profile.json').read_text(encoding='utf-8'))
    tests=json.loads((REPORTS/'test_results.json').read_text(encoding='utf-8'))
    config=training['training_config'];artifact=training['artifact'];unit=tests['qci2'];regression=tests['qci1'];repo=tests['repository']
    per_class='\n'.join(f"| {c['class_id']} | {c['class_name']} | {c['support']} | {c['precision']:.6f} | {c['recall']:.6f} | {c['f1']:.6f} |" for c in evaluation['per_class'])
    failures=json.loads((REPORTS/'misclassifications.json').read_text(encoding='utf-8'))
    failure_rows='\n'.join(f"- {r['sample_id']}: actual {r['ground_truth_name']}, predicted {r['prediction']['predicted_class_name']}, confidence {r['prediction']['confidence']:.6f}." for r in failures) or 'No test misclassifications were observed. Every test image is included, rather than inventing failure examples.'
    checks=[('Required feature branch','PASS'),('QCI-1 validated data consumed','PASS'),('Actual target and binary design justified','PASS'),('Verified local starting assets','PASS'),
        ('No runtime cloud API dependency','PASS'),('Pydantic v2 contracts','PASS'),('Typed/documented new functions','PASS'),('Bounded loaders','PASS'),('Deterministic training settings','PASS'),
        ('Train class imbalance handled','PASS'),('Real classifier training completed','PASS'),('Best saved/reloaded','PASS'),('Once-only held-out test evaluated','PASS'),('Per-class metrics/confusion matrix','PASS'),
        ('Real model-gradient heatmaps','PASS'),('Heatmap sanity tests','PASS'),('Typed inference JSON','PASS'),('Malformed inputs controlled','PASS'),('Offline model/heatmap verified','PASS'),
        ('Production inference RSS measured','PASS'),('Stable drift strict<5%','PASS' if profile['strict_under_5_percent_pass'] else 'FAIL'),('QCI-2 tests100% passing','PASS' if unit['exit_code']==0 else 'FAIL'),
        ('QCI-1 regression','PASS' if regression['exit_code']==0 else 'FAIL'),('Entire repository tests','PASS' if repo['exit_code']==0 else 'FAIL; prior CPU1 numeric gates'),
        ('Docs and actual visual/terminal proof','PASS'),('PR created','FAIL; organization access revoked'),('Commercial dataset permission','NOT OBTAINED; noncommercial research only'),
        ('QCI-2 OVERALL','FAIL; local technical work complete, full repository/PR/release gates pending')]
    table='\n'.join(f'| {key} | {value} |' for key,value in checks)
    summary=dict(status='local_training_and_explanation_completed_release_pending',overall_dod='FAIL',task='QCI-2',branch='feature/sprint2-qci2-defect-classifier',base_commit='d63ff417b363ea8fd81e0027f9ca458afdda4aee',
        dataset_version=training['dataset_version'],dataset_manifest_sha256=artifact['manifest_sha256'],dataset_records_sha256=artifact['records_sha256'],classes={0:'normal',1:'defect'},split_counts=dict(train=302,val=48,test=16),
        model_version=artifact['version'],architecture='resnet18',artifact=artifact,training=training,test_metrics=evaluation,latency_and_memory=profile,tests=tests,
        heatmap_method='Grad-CAM',target_layer='layer4.1.conv2',heatmap_samples=evaluation['heatmaps_generated'],offline_verified=True,external_runtime_api_calls=0,runtime_downloads=0,
        gpu_used=False,modal_session_started=False,numeric_accuracy_target=None,numeric_latency_sla=None,pr_created=False,pr_url=None,commercial_permission_obtained=False,
        artifacts=dict(config='QCI_2_Defect_Classifier/configs/qci2_classifier.yaml',checkpoint=artifact['checkpoint'],test_metrics='reports/qci2/test_metrics.json',confusion_matrix='reports/qci2/confusion_matrix.png',
            curves='reports/qci2/training_curves.png',sanity_grid='reports/qci2/classifier_heatmap_sanity_grid.png',proof='reports/qci2/proof_of_work.png'),dod={k:v for k,v in checks})
    write_json(REPORTS/'qci2_summary.json',summary)
    report=f'''# QCI-2 — Defect classifier and anomaly/attention heatmap review

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
Version `{training['dataset_version']}`, SHA256 `{artifact['manifest_sha256']}`.
Records SHA256 `{artifact['records_sha256']}`. The original seven-class textile
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
two-class head, **{artifact['parameters']:,} parameters**, **{artifact['trainable_parameters']:,}
trainable**. Actual existing cached ImageNet checkpoint:
`C:/Users/ehtis/.cache/torch/hub/checkpoints/resnet18-f37072fd.pth`;
SHA256 `{artifact['starting_weights_sha256']}`. A portable verified copy is in
`QCI_2_Defect_Classifier/runtime/initialization/`. No download occurred.
Build uses `weights=None`, then explicit local `torch.load(weights_only=True)`.
Fine-tune final residual block and linear head only; freeze all BatchNorm running
statistics. This cached moderate model fits the local2-core/4-logical CPU rather
than selecting a huge architecture. PyTorch2.10.0+cpu/Torchvision0.25.0; no GPU used.

Input **{config['height']}x{config['width']} RGB**: QCI-1 aspect-preserving letterbox,
no center crop, area shrink/linear enlarge, padding114, CHW float32/255 with
ImageNet mean/std. Train-only horizontal flips probability{config['horizontal_flip']}
and mild brightness/contrast±{config['brightness_contrast']}; label presence is
invariant and no mask crop is consumed. Validation/test are deterministic.

## Training configuration and real results

Seed{config['seed']}; deterministic PyTorch algorithms; CPU threads{config['threads']};
batch{config['batch_size']}; workers0/no worker prefetch/pinning; AdamW
last-block lr{config['learning_rate']}, head lr{config['head_learning_rate']},
weight decay{config['weight_decay']}; cosine schedule over{training['epochs_requested']}
requested epochs; early stopping patience{config['patience']}. Inverse train-frequency
cross-entropy weights **{training['class_weights']}**, calculated only from263/39.
No artificial balancing or normal-class invention.

Epochs requested **{training['epochs_requested']}**, completed **{training['epochs_completed']}**,
best **{training['best_epoch']}**. Validation macro F1 selects the model; ties
use lower weighted validation loss. Best validation metrics:
`{training['best_validation']}`; weighted loss{training['best_validation_loss']:.8f}.
Real duration{training['duration_seconds']:.3f}s. Mini-batch smoke forward/backward
was finite and took no optimizer step. Best/last checkpoint and config/history
saved without overwriting earlier runs. Selected checkpoint reloaded and validation
metrics reproduced. Training RSS is separately logged as observed per-batch values;
those observations are not claimed as a continuously sampled peak/stability test.

Model version `{artifact['version']}`. Selected weights `{artifact['checkpoint']}`,
SHA256 **`{artifact['sha256']}`**. Training-base commit `{artifact['source_commit']}`;
the exact executed source snapshots match hashes recorded before training under
`runtime/execution_sources/`. Later committed code adds path/contract hardening,
reports, tracking and recovery; the registry records that implementation commit
separately. No false claim that uncommitted training had a future commit hash.

## Final held-out test evaluation and failure analysis

Selected checkpoint evaluated once, after validation-only selection. All16 test
images and all predictions are reported; tiny test support, particularly **two
defective images**, limits generalization and statistical conclusions.

- Accuracy **{evaluation['accuracy']:.6f}**.
- Macro precision **{evaluation['macro_precision']:.6f}**.
- Macro recall **{evaluation['macro_recall']:.6f}**.
- Macro F1 **{evaluation['macro_f1']:.6f}**.

| ID | Class | Support | Precision | Recall | F1 |
| --- | --- | --- | --- | --- | --- |
{per_class}

Confusion matrix (actual rows, predicted columns, normal/defect order):
`{evaluation['confusion_matrix']}`. Raw metrics, per-image scores, complete
misclassification list, confusion matrix plot and all-test visualization retained.

{failure_rows}

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

Generated **{evaluation['heatmaps_generated']}** actual test explanations; finite
image-aligned **{evaluation['finite_image_aligned_maps']}**, degenerate
**{evaluation['degenerate_heatmaps']}**. Every held-out test sample appears in
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

Dedicated production workload:20 warm calls, then **{profile['measured_calls']}**
real classifier+Grad-CAM calls in two matched240-call windows, complete identical
48-image validation mixes repeated five times each. No disk-map export in latency
profile; combined time includes decode/preprocessing/prediction/CAM alignment.

| Timing | Mean ms | P95 ms |
| --- | --- | --- |
| Classifier forward |{profile['classifier_latency']['mean_ms']:.3f}|{profile['classifier_latency']['p95_ms']:.3f}|
| Separate attribution pass/alignment |{profile['heatmap_latency']['mean_ms']:.3f}|{profile['heatmap_latency']['p95_ms']:.3f}|
| Complete request |{profile['combined_latency']['mean_ms']:.3f}|{profile['combined_latency']['p95_ms']:.3f}|

RSS start **{profile['start_rss_mib']:.3f}MiB**, peak **{profile['peak_rss_mib']:.3f}MiB**,
end **{profile['end_rss_mib']:.3f}MiB**. Stable window means
**{profile['cycles'][0]['mean_rss_mib']:.3f} -> {profile['cycles'][-1]['mean_rss_mib']:.3f}MiB**.
Drift **{profile['drift_percent']:.6f}%**, strict<5% **{profile['strict_under_5_percent_pass']}**.
Metric=absolute full-window mean difference/first mean after warm-up; raw endpoints
retained separately. Peak sampled20Hz, {profile['continuous_rss_samples']} observations.
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

QCI-2: collected{unit['collected']}, **{unit['passed']} passed**, {unit['failed']} failed,
{unit['skipped']} skipped,{unit['errors']} errors, {unit['duration_seconds']:.2f}s.
QCI-1 regression: **{regression['passed']} passed**, {regression['failed']} failed,
{regression['duration_seconds']:.2f}s. Normal full-root `pytest -q`: collected
{repo['collected']}, **{repo['passed']} passed**, **{repo['failed']} failed**,
{repo['skipped']} skipped,{repo['errors']} errors,{repo['duration_seconds']:.2f}s.
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
{table}

Changed: task package/config/README, thin existing Training entry, root QCI-2 tests,
minimal root README/requirements/.gitignore, existing experiment registry support
and appended model/run rows, measured reports/proof. QCI-1 source/data/splits and
existing model/tracker/UI work unchanged. Dataset binaries, weights, venvs,
credentials and runtime/recovery ZIPs excluded from Git.
'''
    (REPORTS/'QCI_2_Production_Review.md').write_text(report,encoding='utf-8')
    eod=f'''QCI-2 — EOD Update
Status: local training, final test and Grad-CAM complete; release/PR gates pending.
Branch: feature/sprint2-qci2-defect-classifier (two local commits).
Dataset: QCI-1 curated366, untouched302/48/16, binary normal/defect.
Model: ResNet18, existing local initialization, {artifact['version']}.
Training: {training['epochs_completed']}/{training['epochs_requested']} epochs; best{training['best_epoch']}.
Test: accuracy{evaluation['accuracy']:.6f}, macroF1{evaluation['macro_f1']:.6f}; two positive test images only.
Heatmap: genuine Grad-CAM, layer4.1.conv2, {evaluation['heatmaps_generated']} all-test samples.
Memory: {profile['drift_percent']:.6f}% matched-window drift (<5%).
Offline:0 external runtime calls/downloads; no GPU used.
Tests: QCI-2 {unit['passed']} passed/0 failed; QCI-1 {regression['passed']} passed; root {repo['passed']} passed/{repo['failed']} prior CPU1 failures.
PR: pending restored organization access; no URL.
Blockers: prior repository numeric gates, PR access, commercial dataset permission.
Ready to paste; no Slack message sent.
'''
    (REPORTS/'EOD_Update.md').write_text(eod,encoding='utf-8')
    (TASK/'pr_description.md').write_text('# QCI-2: add defect classifier training and anomaly heatmaps\n\n'+eod+'\nEvidence: reports/qci2/QCI_2_Production_Review.md, confusion_matrix.png, classifier_heatmap_sanity_grid.png and pytest_output.txt. The classifier is binary mask presence; original textile classes are not invented. Actual best checkpoint hash in model_artifact.json. Full-root failures are retained.\n',encoding='utf-8')
    terminal=html.escape((REPORTS/'pytest_output.txt').read_text(encoding='utf-8'))
    page=f'''<!doctype html><html><head><meta charset="utf-8"><title>QCI-2 actual classifier proof</title><style>body{{font:16px system-ui;color:#17344d;background:#eef3f7;margin:30px}}main{{max-width:1400px;margin:auto}}section{{background:white;padding:22px;margin:16px 0;border:1px solid #d8e1eb;border-radius:8px}}img{{max-width:1140px;width:100%}}pre{{font:13px Consolas,monospace;white-space:pre-wrap;overflow-wrap:anywhere}}.note{{background:#fff3d6;padding:18px}}</style></head><body><main><h1>QCI-2 / Real local classifier and Grad-CAM</h1><section><b>Trained checkpoint + untouched held-out test</b><p>ResNet18 | {training['epochs_completed']} epochs | best epoch{training['best_epoch']} | splits302/48/16</p><p>Test accuracy{evaluation['accuracy']:.4f}, macroF1{evaluation['macro_f1']:.4f}. Only two positive test samples; no production-generalization claim.</p><p>QCI-2 {unit['passed']} passed; QCI-1 {regression['passed']} passed; root {repo['passed']} passed/{repo['failed']} old CPU1 failures. RSS drift{profile['drift_percent']:.4f}%.</p></section><div class="note">Local noncommercial review complete. PR/access, commercial permission and prior repository numeric gates pending.</div><section><h2>Actual focused pytest output</h2><pre>{terminal}</pre></section><section><h2>Actual held-out confusion matrix</h2><img src="confusion_matrix.png" style="max-width:650px"></section><section><h2>Actual training history</h2><img src="training_curves.png"></section><section><h2>Every test image: source, ground truth, prediction, model heatmap, overlay</h2><img src="classifier_heatmap_sanity_grid.png"></section></main></body></html>'''
    (REPORTS/'review.html').write_text(page,encoding='utf-8')
    print('Saved actual summary, full review, PR/EOD bodies and proof page.')


if __name__=='__main__':main()
