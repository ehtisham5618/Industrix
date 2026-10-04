# CME-OPT1 execution results

Overall: **PASS**. Dataset-format validation: **PASS** (documented inherited lineage overlap remains).
Qualifying verified negatives: chemical 142, smoke 96, combined 238. >=150: **PASS**.

Unique reviewed real negative source image hashes used in train augmentation: observed errors and verified visual confusers under task section 13 (causes or could cause); derivatives and positives excluded

Observed errors: 28; verified visual confusers: 210; new real reference photos: 205.

| ID | Class | Train before | Added | Train after | Val | Test |
|---|---|---:|---:|---:|---:|---:|
| 0 | baekra | 490 | 0 | 490 | 79 | 24 |
| 1 | color issues | 464 | 0 | 464 | 30 | 21 |
| 2 | contamination | 338 | 0 | 338 | 55 | 17 |
| 3 | cut | 692 | 0 | 692 | 102 | 47 |
| 4 | gray stitch | 666 | 0 | 666 | 87 | 48 |
| 5 | selvet | 841 | 0 | 841 | 121 | 58 |
| 6 | stain | 1925 | 72 | 1997 | 312 | 153 |
| 7 | chemical hazard | 340 | 154 | 494 | 53 | 4 |
| 8 | fire | 501 | 0 | 501 | 92 | 22 |
| 9 | no helmet | 860 | 9 | 869 | 216 | 45 |
| 10 | smoke | 901 | 113 | 1014 | 154 | 51 |
| 11 | water leak | 150 | 4 | 154 | 33 | 8 |

## Target breakdown

```json
{
  "chemical hazard": {
    "observed_verified_hard_negative_images": 0,
    "observed_after_640_reference_check": 4,
    "potential_confuser_images": 142,
    "hard_positive_images": 25,
    "augmented_real_images": 134,
    "mosaics": 41,
    "synthetic_overlays": 0
  },
  "smoke": {
    "observed_verified_hard_negative_images": 4,
    "observed_after_640_reference_check": 24,
    "potential_confuser_images": 92,
    "hard_positive_images": 25,
    "augmented_real_images": 65,
    "mosaics": 48,
    "synthetic_overlays": 12
  }
}
```

## Transforms

{"mosaic": 89, "color_jitter": 79, "hsv": 80, "chemical_sheen": 40, "smoke_overlay": 12}

## Integrity

```json
{
  "evaluation_bytes_unchanged": true,
  "all_original_image_label_bytes_retained": true,
  "original_combined_dataset_bytes_retained": true,
  "photometric_label_bytes_unchanged": true,
  "all_sources_train_and_hash_verified": true,
  "all_output_hashes_verified": true,
  "no_augmented_source_evaluation_family_overlap": true,
  "known_original_filename_family_cross_split_overlap": {
    "train-val": 335,
    "train-test": 188,
    "val-test": 106
  },
  "note": "Filename families cover known _aug and Roboflow derivatives, not unknown renamed derivatives."
}
```

Corrupt: 0; invalid labels: 0; missing labels: 0; orphan labels: 0; exact cross-split duplicates: 0.

Existing rounded-edge boxes accepted within documented 0.0001 normalized tolerance: 494.

## Follow-up

Obtain peer review and evaluate domain transfer after retraining. Rebuild inherited splits by source family and audit incomplete hazard labels before claiming accuracy gains. The dataset optimization deliverable does not certify detector improvement.

## Limitations

- Observed detector errors and verified could-cause visual confusers are reported separately; count follows task section 13, and excludes positives/derivatives.
- Initial mining used 320 pixels; additional full-source 640-pixel mining and reference measurements screen failures, not deployment accuracy.
- Some unmatched smoke predictions overlap visible unlabelled smoke; excluded from negative selection.
- Licensed outdoor references are supplemental negatives; domain transfer to textile factories is unproven.
- Verification was performed by Codex visual review, not by a human peer reviewer.
- No proof of model accuracy improvement without follow-up retraining/evaluation.
