The previous draft stopped at four verified negative sources. This revision
adds 205 independent licensed real photos with hash-bound visual review,
bringing the final selection to **238 verified negative-source examples**
(142 chemical, 96 smoke): **28 observed detector errors and 210 visual confusers**
under section 13's "causes or could cause" definition. Positives and derivatives
are excluded. Review was performed by Codex with source metadata, not by a human
peer reviewer.

The final training set adds 505 images: 205 real references plus 300 deterministic
derivatives. Train 4,974 -> 5,479; val 777 and test 334 are byte-identical. Chemical
annotations 340 -> 494; smoke 901 -> 1,014. All 12 classes remain represented and
their unequal counts are disclosed. No accuracy improvement is claimed.

Color jitter 79; HSV 80; fluorescent/IR-like sheen 40; Mosaic 89; smoke overlay 12.
Smoke overlays stay in real smoke boxes. Source hashes/families and reference
deduplication guard evaluation leakage. Authors, licenses, source URLs, explicit
absence review and negative regions accompany all 205 added real sources.

Validation: PASS, 6,590 images /10,352 annotations, zero corrupt images, invalid
labels, missing pairs or exact cross-split duplicates. Twelve tests pass.
Original image/label bytes are retained. CME-3 records CMEOPT1-DATA-002 while
preserving the earlier incomplete run.

Evidence under CME_OPT1_Hard_Negative_Augmentation/reports/:
- RESULTS.md and completion_status.json: acceptance count and all 12 classes.
- class_balance_before_after.png and qc_contact_sheet.png.
- reference_contact_sheet_0000.png through reference_contact_sheet_0200.png.
- reference_review_decisions.csv and reference_attributions.csv.
- reviewed_selection_v3.csv and augmentation_manifest.csv.
- reference_detector_summary.json: actual 640-pixel reference measurements.
- deployment_resolution_candidates.json and deployment_resolution_reviews.csv: full-source 640-pixel audit.
- validation_terminal_output.txt, statistics_terminal_output.txt, tests_terminal_output.txt.
- lineage_audit.json: unchanged original/evaluation bytes.

The supplied required branch is feature/atlantis-dataset-augmentation. This PR
keeps its current staging target. The rejection bodies provide governance checks,
with no inline technical comments. The draft rejection is addressed by marking
the completed revision Ready for Review. Peer approval remains pending from
muhammadaliqamar; previous changes-requested reviews are not dismissed.

Inherited concerns: source-family overlaps (335 train/val, 188 train/test,
106 val/test), some incomplete smoke labels, documented 0.0001 edge tolerance.
The outdoor references supplement factory data; domain transfer is unproven.
Full datasets/weights stay ignored. Reproduction and attribution requirements
are documented in the separate task folder's README. No merge requested.
