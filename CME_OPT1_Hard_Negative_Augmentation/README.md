# CME-OPT1: targeted chemical and smoke augmentation

Technical acceptance passes with **238 unique verified negative source images**:
142 chemical and 96 smoke examples, including **28 observed errors and 210 verified
visual confusers**. The count follows task section 13: a hard negative causes
**or could cause** a false prediction. These are not 238 observed failures.
Positives and generated copies never contribute. Codex performed visual review
with source metadata; human peer approval remains pending.

Executed October 4, 2026. The earlier shortfall remains in Git history and
CMEOPT1-DATA-001. The completed revision is CMEOPT1-DATA-002.

## Dataset and results

Original source: Hazard_Expansion/content_runtime/combined_dataset (existing CME-1
combined_dataset.zip extraction). Reviewed source:
Hazard_Expansion/content_runtime/combined_dataset_reviewed_v3_final.
Final: Hazard_Expansion/content_runtime/combined_dataset_augmented_v3,
version **combined-12class-v3-hardnegative**.

Added **505 training images**: 205 independent new real photos and 300 derivatives.
Train: 4,974 -> 5,479; val: 777; test: 334. Final: **6,590 images / 10,352
annotations**. Validation PASS: zero corrupt images, invalid labels, missing pairs
or exact cross-split duplicates. All original image/label bytes and evaluation
are preserved. All 12 classes remain represented; counts are unequal.

Chemical annotations: 340 -> 494; smoke: 901 -> 1,014. The 267 added target positive
annotations remain separate from negative-source examples. IDs remain baekra=0,
color issues=1, contamination=2, cut=3, gray stitch=4, selvet=5, stain=6,
chemical hazard=7, fire=8, no helmet=9, smoke=10, water leak=11.

Selected detector: cme1-expanded-12class-v1, Backend/best.pt, SHA-256
6e64a19d83f09b7b2a92fddf23a5161734295c2a183af08ee1802065bd36995b.

## Verification and counting

Local selection contains 29 verified textile-stain confusers, four observed smoke
negatives and 50 annotation-supported hard positives. Of 428 external candidates,
426 downloaded. Visual review excluded uncertain scenes, people, repeat views,
paintings/composites, orbital-film frames and a wildfire-smoke series. Source
deduplication excluded nine otherwise accepted photos. **205 independent real
references** remain: 113 normal water/surface reflections and 92 cloud/lighting
confusers.

Every reference has a SHA-256-bound visual decision, a negative region, explicit
absence of all 12 classes, author, source URL and license. They receive empty YOLO
labels; negative regions are in manifests, not invented hazard boxes. Genuine
labels on original sources remain unchanged. One example is counted per distinct
real source hash actually used in augmentation.

Reference measurement at 640 pixels/confidence 0.15 found four chemical and 20
smoke errors. With the original four smoke negatives, this gives 28 observed
errors. Selection-time manifests classify references as potential confusers;
the final report incorporates the later measurement without counting twice.
An additional full original-training scan at 640 pixels/confidence 0.10 produced
379 candidates, including 53 absent-label predictions. All 53 were visually
reviewed; seven supplemental negative regions were recorded but **not added**
to the completed count. Annotation disagreement alone does not prove absence.

Source discovery used Commons [puddle reflections](https://commons.wikimedia.org/wiki/Category:Reflections_in_puddles)
and [clouds](https://commons.wikimedia.org/wiki/Category:Cumulus_clouds).
Only explicit CC BY, CC BY-SA, CC0 or public-domain licenses were admitted.
Individual photo descriptions, authors and license URLs are retained in
reports/reference_attributions.csv, with a copy in both datasets. Derivatives
retain source license obligations.

## Augmentation and limits

Seed 42 produced color jitter 79, HSV 80, conservative fluorescent/IR-like sheen
40, Mosaic 89 and smoke overlay 12. Mosaic uses reviewed training partners,
scaled/translated/clipped boxes and a two-pixel minimum. Smoke overlays stay
inside real existing smoke annotations. Photometric label bytes remain unchanged.
Source hashes and known filename families block new evaluation leakage. Quality
checks reject extreme brightness, invalid/tiny boxes and duplicate outputs.

Inherited concerns remain: 335 train/val, 188 train/test and 106 val/test shared
source families; some incomplete smoke annotations; exporter-rounded edges using
a documented 0.0001 normalized tolerance. Original splits/labels are preserved.
Outdoor references supplement factory data; domain transfer is unproven. Rebuild
inherited source-family splits and audit annotations before evaluating model
gains. No retraining, detector replacement or accuracy improvement is claimed.

## Reproduction

Run from the repo root with existing OpenCV, NumPy, PyYAML, Pillow, Matplotlib,
Ultralytics and PyTorch. Collection needs network access. Fresh outputs are
required; scripts refuse to overwrite datasets. Reuse review decisions only when
downloaded bytes match their hashes; changed photos require new visual review.

    python CME_OPT1_Hard_Negative_Augmentation/scripts/collect_reference_negatives.py
    python CME_OPT1_Hard_Negative_Augmentation/scripts/ingest_reviewed_references.py --dataset Hazard_Expansion/content_runtime/combined_dataset --output Hazard_Expansion/content_runtime/combined_dataset_reviewed_v3_final
    python CME_OPT1_Hard_Negative_Augmentation/scripts/check_reference_detector.py
    python CME_OPT1_Hard_Negative_Augmentation/scripts/run_acceptance.py
    python Experiment_Tracking/scripts/validate_registry.py

run_acceptance.py executes augmentation, required validator/statistics CLIs,
evidence generation and tests, preserving actual output and exit codes as LF
lines. Twelve tests cover deterministic CLI output, Mosaic geometry, smoke
semantics, unchanged labels/evaluation, leakage refusal, attribution deduplication
and hash-bound all-class-negative review.

## Evidence and PR

- [Results and all 12 classes](reports/RESULTS.md)
- [Acceptance status](reports/completion_status.json)
- [Class balance graph](reports/class_balance_before_after.png)
- [QC](reports/qc_contact_sheet.png)
- [Reviewed selection](reports/reviewed_selection_v3.csv)
- [New real sources](reports/reference_ingestion_manifest.csv)
- [Visual decisions](reports/reference_review_decisions.csv)
- [Attribution/licenses](reports/reference_attributions.csv)
- [First reference sheet](reports/reference_contact_sheet_0000.png)
- [Augmentation lineage](reports/augmentation_manifest.csv)
- [Preservation audit](reports/lineage_audit.json)
- [Terminal validation](reports/validation_terminal_output.txt)
- [Checklist](reports/FINAL_CHECKLIST.md)

[PR #1](https://github.com/devlogixtechnology/industirx/pull/1) uses the explicitly
required feature/atlantis-dataset-augmentation branch and currently targets
staging. The branch was created and pushed during initial implementation to
isolate task changes until review and merge. Previous reviews contain governance
checks, with no inline technical comments. Ready-for-review status addresses the
draft rejection; peer approval must come from a teammate.
