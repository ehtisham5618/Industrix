# CME-OPT2 — YOLOv8s focal-loss fine-tuning

This task uses the validated CME-OPT1 `combined-12class-v3-hardnegative` dataset.
The local data YAML is `Hazard_Expansion/content_runtime/combined_dataset_augmented_v3/data.yaml`.
Training and held-out test comparison are separate steps. The historical
Experiment C checkpoint is backed up before any deployment change.

The actual execution evidence is written to `reports/`. The evaluation report
and JSON determine acceptance from measured test metrics, never typed targets:
chemical hazard AP50 ≥65% and overall 12-class mAP50 ≥72%.

## Reproduce

From the repository root, use the configured Modal account:

```powershell
$env:PYTHONIOENCODING = 'utf-8'
python -m pip install modal ultralytics==8.4.24
python -X utf8 CME_OPT2_Model_Fine_Tuning/prepare_inputs.py
python -X utf8 -m modal run --detach CME_OPT2_Model_Fine_Tuning/modal_runner.py --mode smoke
python -X utf8 -m modal run --detach CME_OPT2_Model_Fine_Tuning/modal_runner.py --mode train
python -X utf8 -m modal run --detach CME_OPT2_Model_Fine_Tuning/modal_runner.py --mode followup
python -X utf8 -m modal run --detach CME_OPT2_Model_Fine_Tuning/candidate_runner.py
python -X utf8 -m modal run CME_OPT2_Model_Fine_Tuning/candidate_runner.py --mode select
python -X utf8 -m modal run --detach CME_OPT2_Model_Fine_Tuning/selected_runner.py
python -X utf8 CME_OPT2_Model_Fine_Tuning/fetch_artifacts.py
python -X utf8 CME_OPT2_Model_Fine_Tuning/finalize.py
python Experiment_Tracking/scripts/validate_registry.py
python CME_OPT2_Model_Fine_Tuning/verify_acceptance.py
```

Run names are protected against overwriting. Reproduction in an already used
volume requires a new run name/volume rather than overwriting the official run.
Notebook 03 invokes the same smoke/training implementation. Notebook 04 consumes
the resulting `/training_contract.json`, evaluates both models, fetches the
evidence and verifies export. Historical CME-1 cells remain available but are
disabled by default, so running all cells does not retrain earlier tasks.

The cloud image pins Python 3.11, Ultralytics 8.4.24, PyTorch 2.10.0,
torchvision 0.25.0 and MLflow 2.22.2. Actual CUDA/GPU details are captured at run
time; the configured GPU is A10G. There are no credentials in this directory.
The GPU worker scales down after 600 seconds of inactivity, has zero minimum
containers, and the CLI invocation closes after its work finishes.
A utilization watchdog also terminates a stalled active job after ten continuous
minutes at zero GPU utilization, so an active-but-idle process cannot retain it.
GPU runs use detached mode to survive a local client disconnect. If a detached
client command fails, inspect its app/container before retrying to avoid
launching a duplicate GPU job. Stop completed task apps explicitly with
`python -m modal app stop --yes APP_ID`.

## Recorded experiments and recovery

Official A retains the requested COCO initialization and default classification
gain .5. Its validation mAP50 was only 16.4% at epoch 12, versus the registered
Experiment C historical 76.6%. This validation evidence motivated B:
initialization from the verified 12-class Experiment C checkpoint and `cls=2.0`
to compensate the focal alpha weighting. Gamma, alpha, SGD, cosine schedule,
batch, image size, seed, epoch limit and patience are the same. Each run retains
its own weights, CSV, config and validation plots; final selection uses
validation and no test feedback.

A client connection failure interrupted A after epoch 19; B's first attempt
failed during startup before training. The interruption is recorded in
`reports/infrastructure_recovery.json`. A resumes with model, optimizer, scaler
and scheduler restored, using:

```powershell
python -X utf8 -m modal run --detach CME_OPT2_Model_Fine_Tuning/resume_runner.py
```

Upstream augmentation RNG and early-stopping in-memory state restart on resume;
the continuation is not claimed to be bitwise identical to an uninterrupted
run. `execution_sources/official_A/` preserves the original source snapshot.
Contracts bind executed source files and checkpoints to their SHA256 hashes.

B early-stopped at 11 epochs; its best validation checkpoint had overall
77.3% mAP50 but chemical AP50 only 45.4%. C therefore retains Experiment C
initialization, uses AdamW `lr0=.001`, zero bias warmup and the original global
`cls=.5`, and weights classification focal loss by 4 for chemical / 2 for smoke /
1 for other classes. This controlled variant is explicitly distinct from
official A's required `lr0=.01` configuration. Three configurations are the
maximum; the test split does not guide any change.

The first C worker spent ten minutes idle waiting on cold volume reads; the
watchdog stopped it before any epochs. The retry verifies the sealed ZIP on CPU
before allocating a GPU and trains from a locally extracted copy in `us-east`.
Its ZIP SHA256 and every original validation/test file hash are checked. This
changes storage placement, not dataset contents. The final evaluation uses the
same verified archive and local storage. The stopped-worker log is retained.

## Loss and scheduler

`focal_trainer.py` replaces only the elementwise classification BCE callable.
The upstream assignment, target-score normalization, box regression and DFL
are unchanged. Gamma 1.5 / alpha .25 match the upstream focal defaults. The
upstream `FocalLoss` cannot be substituted directly because it reduces across
classes; the replacement retains the shape the detection criterion expects.
Tests compare actual box/DFL components and classification gradients.

SGD is explicit to prevent `optimizer=auto` overriding `lr0`. Cosine scheduling
uses `lr0=.01` and final factor `lrf=.001`, so the theoretical endpoint is
`.00001`. Actual epoch/parameter-group rates, including warmup and early stop,
are recorded independently. `config.yaml` contains the complete overrides.

## Artifacts and lineage

Datasets, full raw runtime logs, checkpoints and local MLflow state are ignored.
The persistent Modal volume is `industirx-cme-opt2`; it retains the baseline,
official run, evaluation evidence and the existing CME-3 MLflow experiment.
Lightweight results, plots and registries are committed.

Experiment C's historical 49.1327% chemical AP is a validation metric. Both
models are evaluated anew on identical original test bytes. Only four chemical
objects exist in that test split, limiting statistical confidence. Existing
source-family overlap predates CME-OPT1; no new overlap or split changes are
introduced by this task. Outdoor reference negatives also limit claims of
factory generalization.

Selection first requires validation mAP50 >= .72, then ranks chemical AP50,
with overall mAP50-95 as a tie-breaker. If no run passes the guard, it selects
the highest validation mAP50-95 and records the shortfall. The test split is not used for parameter
tuning. The selected model is exported as required, with the original deployment
backed up. Numerical gate failures are explicitly recorded as a target shortfall
even when the selected checkpoint has been exported; export never implies
acceptance. Significant per-class regressions are reported.
All registered metrics and checkpoint hashes come from actual artifacts.

Recorded test result: **CME-OPT2 OVERALL: FAIL**. Chemical AP50 is 42.391%
(required 65%); overall mAP50 is 78.156% (required 72%). Smoke AP50 declines
from 61.489% to 54.516%, and cut AP50 declines by 10.648 percentage points.
The selected checkpoint is exported and registered as `deployed_target_shortfall`;
it has not satisfied the accuracy definition of done. See
[`reports/CME_OPT2_Evaluation_Report.md`](reports/CME_OPT2_Evaluation_Report.md)
and [`reports/acceptance_audit.json`](reports/acceptance_audit.json).

## Verification

```powershell
python CME_OPT2_Model_Fine_Tuning/test_focal_training.py
python -m compileall -q CME_OPT2_Model_Fine_Tuning
python Experiment_Tracking/scripts/validate_registry.py
```
