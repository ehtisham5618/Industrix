Hardware sizing guide and formal hazard taxonomy, both derived from and validated against the repository.

**What changed**
- `docs/deployment/HARDWARE_SIZING_GUIDE.md`: verified workload facts, measured evidence (labelled with source/conditions), RAM/CPU/storage sizing method, development / small-edge / multi-stream / GPU profiles, tested-vs-untested compatibility, benchmark procedure, open acceptance criteria.
- `docs/specifications/HAZARD_TAXONOMY.md` + `hazard_taxonomy.v1.json` (v1.0.0): separate namespaces for the 12-class detector and the 2-class QCI-2 classifier; definitions, distinctions (fire/smoke, water/chemical, helmet), downstream compatibility, versioning policy, open conflicts.
- `FDD_2_Hardware_Taxonomy/`: Pydantic validator cross-checking the manifest against the data config, class constants, EAP-2 baseline, OpenVINO metadata, thresholds and SED-2 severity rules; hardware probe; 21 tests; CI job `taxonomy`.

**Evidence:** taxonomy CONSISTENT; probe on i5-7200U: PyTorch FP32 p50 388 ms / p95 778 ms (2.25 img/s, peak 457 MB), OpenVINO INT8 p50 291 ms / p95 510 ms (2.95 img/s, peak 336 MB); FDD-2 tests 21/21; repository 627 passed / 2 baseline CPU1 failures.

**Open:** no target edge device or GPU benchmark; no approved latency/camera/memory targets; taxonomy conflict C-1 (`chemical hazard` positives mostly from the Water Leaks source family) and pending textile definitions. No model, API or dependency changes.

Evidence: `reports/fdd2/FDD_2_Review.md`, `reports/fdd2/fdd2_summary.json`.
