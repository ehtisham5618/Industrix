# IndustriX Hazard & Defect Taxonomy Specification

| | |
|---|---|
| Taxonomy version | **1.0.0** (schema `fdd2-taxonomy-schema-v1`) |
| Status | Draft for review |
| Machine-readable source | [`hazard_taxonomy.v1.json`](hazard_taxonomy.v1.json) |
| Validation | `python -m FDD_2_Hardware_Taxonomy.taxonomy` and `pytest FDD_2_Hardware_Taxonomy/tests` |

The repository is the source of truth. Class IDs and names below are copied from
`Hazard_Expansion/configs/12class_data.yaml`, the EAP-2 baseline manifest, `ESE_CPU1_Quantization/common.py`
and the OpenVINO export metadata, and are re-checked automatically on every test run.

## 1. Model namespaces
IndustriX has **two independent class namespaces**. A class ID is meaningful only together with
its `model_id`: detector ID 0 (`baekra`) and classifier ID 0 (`normal`) are unrelated. There is no
cross-model ID mapping and none may be assumed.

| model_id | model_version | Task | Classes |
|---|---|---|---|
| `industrix-detector` | `cme-opt2-focal-cosine-12class-v1` (`Backend/best.pt`, SHA256 `c4aba081…0061`) | YOLOv8s object detection, boxes | 12 |
| `qci2-surface-classifier` | `qci2-kolektor-resnet18-v1` (local weights, CC BY-NC-SA 4.0 data) | ResNet18 binary image classification | 2 |

### 1.1 `industrix-detector`
| ID | class_name (exact) | Domain | Alert class | Confidence threshold (configured) | Severity (SED2-alert-escalation-v1) | Definition status |
|---:|---|---|:-:|---|---|---|
| 0 | `baekra` | textile defect | no | not configured (API default 0.25) | not configured | **pending** |
| 1 | `color issues` | textile defect | no | not configured | not configured | provisional |
| 2 | `contamination` | textile defect | no | not configured | not configured | provisional |
| 3 | `cut` | textile defect | no | not configured | not configured | provisional |
| 4 | `gray stitch` | textile defect | no | not configured | not configured | **pending** |
| 5 | `selvet` | textile defect | no | not configured | not configured | **pending** |
| 6 | `stain` | textile defect | no | not configured | not configured | provisional |
| 7 | `chemical hazard` | industrial safety | yes | 0.25 | warning → critical after 3 s | provisional |
| 8 | `fire` | industrial safety | yes | 0.25 | warning → critical after 3 s | provisional |
| 9 | `no helmet` | industrial safety | yes | 0.25 | warning → critical after 10 s | provisional |
| 10 | `smoke` | industrial safety | yes | 0.50 | info → warning 2 s → critical 8 s | provisional |
| 11 | `water leak` | industrial safety | yes | 0.50 | info → warning after 5 s | provisional |

Thresholds come from `Confidence_Calibration/configs/calibrated_thresholds.yaml` (temporal
confirmation: 3 of 5 frames, cooldown 10, clear 5), severities from
`SED_2_Alert_Escalation/configs/severity_rules.yaml` (with geofence zone overrides). Textile classes
have no configured alert threshold or severity; none is invented here.

Exact spellings are part of the contract: lowercase, spaces as written (`color issues`, `gray stitch`),
and `selvet` (not "selvedge"). There is **no** "Chemical Leak" class: the class is `chemical hazard`.

### 1.2 `qci2-surface-classifier`
| ID | class_name | Meaning |
|---:|---|---|
| 0 | `normal` | surface image with an empty QCI-1 defect mask |
| 1 | `defect` | surface image with a non-empty defect mask (QCI-3 initial severity `warning`) |
This model is trained on KolektorSDD commutator surfaces, not textiles, and is not part of `/predict`.

## 2. Class definitions and annotation rules
Full inclusion/exclusion criteria, hard negatives and annotation instructions per class are in the
JSON manifest. Definition status:
- **approved**: signed off by the domain owner (none yet).
- **provisional**: engineering working definition grounded in the dataset provenance.
- **pending**: the term is a local/industry label (`baekra`, `gray stitch`, `selvet`) that the repository
  never defines; annotate only by matching the FabricDefectNTU reference examples until the textile
  domain owner supplies a written definition.

General rules:
1. One box per instance; several classes may co-occur in one image (e.g. `fire` and `smoke` as separate boxes).
2. Do not box what cannot be determined. Fully occluded heads, unclear liquids or ambiguous texture are left unlabelled and recorded as "uncertain" in the annotation notes for review, never forced into a class.
3. Low light and partial occlusion: label only if the defining evidence is visible (EAP-1 showed recall drops sharply in very dark images).
4. Textile classes describe the fabric; safety classes describe the scene. A liquid mark *on fabric* is `stain`; liquid on floors or equipment is a safety class.

### Distinctions that must be kept
| Pair | Rule |
|---|---|
| `fire` vs `smoke` | `fire` needs visible flame; `smoke` is the plume. Smoke without flame is never `fire`. Both may be present. |
| `water leak` vs `chemical hazard` | Visual only. The model **cannot identify a chemical**, its toxicity or the cause. See open conflict C-1. |
| `no helmet` vs obscured helmet | Label `no helmet` only when the head is visible and bare. A helmet that may be present but is hidden is **not** `no helmet`. |
| textile defect vs safety hazard | Different domains, no overlap: a textile class is never an alert and a safety class never describes fabric quality. |
| `stain` vs `color issues` vs `contamination` | substance mark vs dye/shade deviation vs foreign material. |

### Prediction versus incident
A detection is a model output with a confidence, not a confirmed event. Alerts require the
configured temporal confirmation (CME-2/CME-OPT3) and SED-2 escalation; an incident is confirmed only
by operator review (IFE-UI2/QCI-5 incident records). The model does not identify people, injuries,
chemicals or root causes.

## 3. Downstream compatibility
| Consumer | Representation | Source |
|---|---|---|
| Model output | integer class index 0–11 | `best.pt` / OpenVINO metadata |
| `POST /predict` | `{"filename", "detections":[{"class_id", "class_name", "confidence", "coordinates":{"x1","y1","x2","y2"}}]}`, confidence in [0,1], pixel boxes | `Backend/main.py`, EAP-2 contract |
| Dashboard | displays `class_name` and `confidence` from `/predict` unchanged | `Frontend/app.py` (FDD-1 compatibility test) |
| `/system/status` | `model_classes` = the 12 names in order | `ESE_CPU1_Quantization/common.py` |
| Alerts / incidents | `class_name` keys for thresholds and severity rules | calibration + SED-2 configs |

Proposed additive fields for a future API version: `model_id`, `model_version`, `taxonomy_version`.
They are **not implemented**; the current `/predict` contract is unchanged by FDD-2.

## 4. Versioning and change management
Semantic versioning of the taxonomy (`MAJOR.MINOR.PATCH`):
| Change | Version | Required actions |
|---|---|---|
| Wording, examples, annotation guidance; definition status pending→provisional→approved | PATCH | review; tests stay green |
| New downstream metadata, new optional fields, new model namespace | MINOR | update manifest + tests; consumers unaffected |
| Rename, renumber, merge, split or remove a class; change a model's class order | MAJOR | dataset re-annotation, model retraining and re-export, new `model_version`, migration of stored incidents and threshold/severity configs, API/dashboard release notes |
Class IDs and names are **never** renumbered or renamed silently. The validator fails when any
authoritative source disagrees with the manifest or when severity rules reference an unknown class.

## 5. Open conflicts and decisions
- **C-1 (chemical vs water):** `chemical hazard` positives originate mostly from the "Water Leaks" source
  family (156 training images) plus CME-OPT1 augmentation; the dataset has no written visual criterion
  separating chemical spills from water. Chemical AP50 is 42.4% (CME-OPT2). Decision needed: define the
  visual criterion and re-annotate, or merge into a generic liquid-spill class (a MAJOR change).
- **C-2:** textile definitions for `baekra`, `gray stitch`, `selvet` are pending the textile domain owner.
- **C-3:** no severity or alerting exists for textile defects; whether defects should alert is undecided.
- **C-4:** QCI-2 is a separate research model (noncommercial data licence); its production role is undecided.

## Glossary
namespace: the set of class IDs of one model · alert class: class configured for temporal confirmation
and escalation · hard negative: a look-alike that must not be labelled as the class · provisional:
working definition pending domain approval.

## Change history
| Version | Date | Change |
|---|---|---|
| 1.0.0 | 2026-10-22 | First formal taxonomy (FDD-2) from repository artifacts |
