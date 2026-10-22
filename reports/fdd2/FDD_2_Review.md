# FDD-2 — Hardware Sizing Guide & Hazard Taxonomy Spec: Review

**Status: IMPLEMENTED — REVIEW BLOCKED** (both specifications and validation are complete; target
edge hardware, GPU path and open taxonomy decisions remain unverified).

## Deliverables
- `docs/deployment/HARDWARE_SIZING_GUIDE.md`: workload facts from code, measured evidence, sizing method, 4 profiles, compatibility matrix (tested / expected / unsupported), benchmark procedure, decision process, open acceptance criteria.
- `docs/specifications/HAZARD_TAXONOMY.md` + `hazard_taxonomy.v1.json` (taxonomy 1.0.0): two namespaces, definitions, distinctions, downstream compatibility, versioning policy, open conflicts.
- `FDD_2_Hardware_Taxonomy/taxonomy.py` (Pydantic v2 schema + cross-checks), `hardware_probe.py`, 21 tests, CI job `taxonomy`.

## Taxonomy validation (actual)
`python -m FDD_2_Hardware_Taxonomy.taxonomy` → **CONSISTENT**: `industrix-detector` 12 classes
(0 baekra … 11 water leak) and `qci2-surface-classifier` 2 classes (0 normal, 1 defect) match the data
config, `ESE_CPU1_Quantization/common.py:NAMES`, the EAP-2 baseline manifest, the local OpenVINO metadata,
the calibrated alert classes/thresholds, the SED-2 severity rules and `QCI_2_Defect_Classifier/common.py`.

## Hardware probe (this host only)
Intel i5-7200U (2C/4T), 15.9 GB RAM, Windows 11, no GPU, shared laptop; 100 iterations after 5 warm-up, batch 1, 640, full predict:
| Backend | p50 | p95 | p99 | Throughput | Model-load RSS | Peak RSS |
|---|---:|---:|---:|---:|---:|---:|
| PyTorch FP32 | 388 ms | 778 ms | 1,287 ms | 2.25 img/s | +131 MB | 457 MB |
| OpenVINO INT8 | 291 ms | 510 ms | 771 ms | 2.95 img/s | +71 MB | 336 MB |

## Tests
- `pytest FDD_2_Hardware_Taxonomy/tests -v -rs`: **21 passed**.
- Full repository suite: 627 passed, 2 failed (pre-existing ESE-CPU1 INT8 size and mAP-drop gates), 12 skipped.
- Org lint gate: 0 findings.

## Not verified / open
Target edge device · GPU/CUDA inference · dashboard RSS · incident storage growth · physical offline ·
GitHub Actions · approved latency/camera/memory targets · taxonomy conflicts C-1…C-4 (see spec).
No model, class map, threshold, API or dependency was changed.
