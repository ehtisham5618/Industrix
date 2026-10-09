# QCI-2: add defect classifier training and anomaly heatmaps

QCI-2 — EOD Update
Status: local training, final test and Grad-CAM complete; release/PR gates pending.
Branch: feature/sprint2-qci2-defect-classifier (two local commits).
Dataset: QCI-1 curated366, untouched302/48/16, binary normal/defect.
Model: ResNet18, existing local initialization, qci2-kolektor-resnet18-v1.
Training: 31/40 epochs; best23.
Test: accuracy1.000000, macroF11.000000; two positive test images only.
Heatmap: genuine Grad-CAM, layer4.1.conv2, 16 all-test samples.
Memory: 0.069702% matched-window drift (<5%).
Offline:0 external runtime calls/downloads; no GPU used.
Tests: QCI-2 32 passed/0 failed; QCI-1 74 passed; root 279 passed/2 prior CPU1 failures.
PR: pending restored organization access; no URL.
Blockers: prior repository numeric gates, PR access, commercial dataset permission.
Ready to paste; no Slack message sent.

Evidence: reports/qci2/QCI_2_Production_Review.md, confusion_matrix.png, classifier_heatmap_sanity_grid.png and pytest_output.txt. The classifier is binary mask presence; original textile classes are not invented. Actual best checkpoint hash in model_artifact.json. Full-root failures are retained.
