# CME-OPT2 final validation checklist

**CME-OPT2 OVERALL: FAIL — chemical AP50 target unmet.**

| Required check | Result |
|---|---|
| Required branch used | PASS |
| CME-OPT1 augmented dataset used | PASS |
| 12-class mapping verified | PASS |
| YOLOv8s pretrained starting weights used | PASS |
| Focal Loss implementation verified as active | PASS |
| Focal gamma/alpha documented | PASS |
| DFL not confused with classification Focal Loss | PASS |
| Cosine LR scheduler verified | PASS |
| lr0=0.01 recorded | PASS |
| lrf=0.001 recorded | PASS |
| Actual final LR interpretation documented | PASS |
| Explicit optimizer configured | PASS |
| imgsz=640 | PASS |
| batch=16 | PASS |
| epochs=50 max | PASS |
| patience=10 | PASS |
| Smoke test completed | PASS |
| Official training run completed | PASS |
| Test split evaluation completed | PASS |
| Experiment C comparison completed | PASS |
| Per-class AP calculated | PASS |
| Chemical AP@50 >=65.0% | FAIL |
| Overall mAP@50 >=72.0% | PASS |
| Confusion matrix generated | PASS |
| Backend/best.pt exported | PASS |
| Exported model smoke-tested | PASS |
| model_registry.csv updated | PASS |
| CME-3/MLflow tracking updated | PASS |
| Evaluation report generated | PASS |
| PR submitted | PASS |
| CME-OPT2 OVERALL | FAIL |

The accuracy failure is a measured result, not a missing execution step. No further training was tuned against the held-out test after its final comparison.

Official A: COCO YOLOv8s initialization, SGD lr0=.01, lrf=.001 factor, cosine, focal gamma=1.5/alpha=.25, max50/patience10, batch16/imgsz640. Completed50/best48; actual last LR=1.9856491500783724e-5 (theoretical endpoint1e-5).

Validation-only selected B: Experiment C initialization, cls=2.0, otherwise the same SGD/focal/cosine settings. Completed11/best1 with early stopping; actual last LR=.009046039886902862. C completed11/best1 with AdamW .001 and chemical/smoke focal class weights4/2; not selected.

Actual GPU environment: Python3.11.12, Ultralytics8.4.24, PyTorch2.10.0+cu128, CUDA12.8, NVIDIA A10 (~24GB).

Dataset `combined-12class-v3-hardnegative`: 5479train / 777val / 334test; `Hazard_Expansion/content_runtime/combined_dataset_augmented_v3/data.yaml`. All2222 original validation/test image and label file hashes are preserved. Twelve-class mapping is recorded in the training contract; chemical ID7, smoke ID10.

Same held-out test results:

| Metric | Experiment C | Selected B | Gate |
|---|---:|---:|---|
| Overall mAP50 | 77.796163% | 78.156058% | >=72% PASS |
| Chemical AP50 | 28.922500% | 42.390880% | >=65% FAIL |
| Smoke AP50 | 61.489185% | 54.515682% | regression |
| Overall mAP50-95 | 48.939467% | 49.093837% | reported |

Historical chemical49.1327% was validation; the baseline test result28.9225% above is the fair comparison. Only4 chemical test objects and inherited source-family overlap limit generalization. Smoke and cut regressions are disclosed in the twelve-class comparison. Visual review also suggests one chimney-smoke test image is semantically ambiguous under its original chemical label; the report records it, and labels and metrics remain unchanged.

Export: selected SHA256 `c4aba081f6357e23a7370a5f7cf98eff2c6faa0c4c20a2d4dcb8bcabdd490061` at ignored `Backend/best.pt`, verified stock loading,12names and CPU inference. Original Experiment C remains backed up at `CME_OPT2_Model_Fine_Tuning/runtime/baseline.pt` and `Modal industirx-cme-opt2:/baseline.pt`.

Registry: three new experiments and model versions; selected version `cme-opt2-focal-cosine-12class-v1`, status `deployed_target_shortfall`. Existing CME-3 MLflow experiment `Vision-Driven-Industrial-Safety`: {"cme_opt2_yolov8s_focal_cosine": "f76ac85ba06f4a9bb8120cf290b9d90e", "cme_opt2_B_expC_focal_cosine": "29ee74e5c2ac4dc3ad68f3aa9352fc4a", "cme_opt2_C_targeted_focal_cosine": "26c086285af34c4dbebea3bd3767e91b"}.

Six unit tests PASS; registry validator PASS (15experiments/7models/3policies). All structural acceptance checks PASS; acceptance command exits1 solely because the chemical target fails. Notebook Python cells compile; evidence cells actually ran locally against completed GPU CLI artifacts. Training cells are not falsely marked executed.

GPU: min_containers=0, scaledown_window=600 and continuous-zero-utilization watchdog600seconds. A real stalled C startup worker was terminated before epochs; its log is retained. Modal container list is empty after completion.

PR submitted: https://github.com/devlogixtechnology/industirx/pull/2 (OPEN, ready for review); base `feature/atlantis-dataset-augmentation` isolates this task from unmerged dataset PR#1. Exactly two task commits are the required delivery; source identity is recorded in all three new experiment rows.

Evidence: [evaluation report](CME_OPT2_Evaluation_Report.md), [actual terminal excerpts](terminal_output.txt), [per-class metrics](per_class_comparison.csv), [acceptance audit](acceptance_audit.json), [deployment verification](deployment_verification.json), [unit tests](unit_test_output.txt), [registry validation](registry_validation.txt).
