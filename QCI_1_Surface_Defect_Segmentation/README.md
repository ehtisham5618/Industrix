# QCI-1 - Surface defect ingestion and segmentation setup

This package extends the existing preprocessing workflow. It uses the real
`final_dataset/data.yaml` seven-class map and preserves existing train/val/test
directories. `Preprocessing/scripts/prepare_surface_segmentation.py` provides the
repository-facing entry point; the task's implementation/evidence/recovery files
remain in this separate task folder.

**The actual textile corpus has detection boxes, not segmentation boundaries.**
The pipeline audits those real images/labels, performs RGB preprocessing and
produces structured reports, but returns **BLOCKED** for segmentation readiness.
It never turns a box into a defect mask or fabricates segmentation ground truth.
At the user's request, genuine publisher KolektorSDD fine masks were downloaded
and prepared separately: 366 verified pairs (47 positive/319 negative). One
ambiguous mask and all 32 exact duplicate copies are quarantined with provenance.
The real-mask CLI returns SUCCESS; its binary defect map is separate from the
textile seven-class map. No segmentation model is trained or claimed.

The publisher license is CC BY-NC-SA 4.0. This is local noncommercial research/
review; commercial deployment needs publisher permission. Source and citation:
https://www.vicos.si/resources/kolektorsdd/ (Tabernik et al., DOI
10.1007/s10845-019-01476-x). Original ZIP SHA256:
65dc621693418585de9c4467d1340ea7958a6181816f0dc2883a1e8b61f9d4dc.

## Run locally

Use the existing backend Python 3.12 environment; Pydantic 2.12.5 is installed.
All required packages must be present before entering offline mode.

```powershell
$taskPython = '.\ESE_CPU1_Quantization\runtime\venv\Scripts\python.exe'
& $taskPython Preprocessing/scripts/prepare_surface_segmentation.py --config QCI_1_Surface_Defect_Segmentation/configs/qci1_segmentation.yaml
& $taskPython Preprocessing/scripts/prepare_surface_segmentation.py --config QCI_1_Surface_Defect_Segmentation/configs/kolektor_segmentation.yaml
& $taskPython -m pytest tests/test_qci1_ingestion.py tests/test_qci1_additional_edges.py tests/test_qci1_decoder_isolation.py tests/test_qci1_acquisition.py -q
& $taskPython -m QCI_1_Surface_Defect_Segmentation.profile_memory --passes 2
& $taskPython -m QCI_1_Surface_Defect_Segmentation.profile_memory --config QCI_1_Surface_Defect_Segmentation/configs/kolektor_segmentation.yaml --passes 2
```

The CLI forbids Python TCP connect/connect_ex throughout execution. There is no
model-loading, HTTP, Kaggle, Roboflow, cloud annotation/storage or runtime install
operation on this path. The cached raw Kaggle archive is not used. GPU/Modal
access is unnecessary, and no GPU session was launched for this task.

If another application has imported Ultralytics first, QCI uses the verified
native Pillow decoder captured by that installed SDK, bypassing its global
install-on-decode-error hook without importing the SDK or altering its function.
Corrupt ordinary images therefore remain structured local failures.

Return codes: **0** ready/SUCCESS; **1** fatal configuration/storage failure;
**2** BLOCKED because source boxes cannot supply segmentation;
**3** PARTIAL/FAILED sample quality gate. Reports are still generated for complete
audits containing rejected samples. Consumers must inspect status and only use
`source_valid && segmentation_valid` records; a completed audit is not a readiness
pass. Expected original textile audit exit: **2**; curated real-mask audit: **0**.

## Typed dataset contract

Pydantic v2 contracts separate `source_valid` from `segmentation_valid`, carry
actual image/annotation paths and hashes, dimensions, split, source geometry,
issues, exact preprocessing transform and optional prepared pair paths. A box-only
record cannot claim segmentation readiness. Unknown foreground pixel counts and
areas remain **null**, not zero. No missing mask path or class is invented.

The canonical source IDs/names come exclusively from source `data.yaml`. YOLO
polygons use source IDs `0..N-1`; derived mask values reserve `0=background` and
map source ID `k` to `k+1`. This declared mask convention preserves source IDs in
metadata while avoiding background/defect collision. The indexed-PNG adapter
requires this same explicit convention; arbitrary RGB masks, binary 0/255 masks
and other conventions are rejected rather than guessed.

YOLO rows with five fields are boxes. Rows with at least three coordinate pairs
are polygons. Invalid/nonfinite IDs, coordinates, zero area, repeated vertices,
self intersections and mixed box/polygon files are rejected. Source integer-valued
class tokens such as `4.0` are normalized using exact Decimal arithmetic with a
recorded warning. The existing YOLO box validator is reused after normalization;
only its documented 1e-4 export-rounding edge tolerance can be clipped. Source
files are never rewritten.

Empty YOLO labels default to **box negatives**, which do not establish pixel-level
background truth. For a genuine YOLO segmentation dataset, explicitly set
`empty_yolo_annotation_kind: polygon` to preserve declared negative annotations.
Different-class polygon overlaps are rejected; same-class overlaps are unioned.
Rasterization rounds normalized coordinates times image width/height, clips to
the pixel grid, and uses OpenCV's inclusive polygon fill convention.

## Preprocessing and outputs

RGB aspect-preserving letterboxing to 640x640 uses area interpolation for shrinking
and linear interpolation for enlargement, with image padding 114. Masks use
**nearest neighbor**, padding class 0, and retain categorical values. Normalized
model-input tensors are contiguous RGB float32 CHW divided by 255. Exported image
files remain RGB uint8 PNG; downstream loading applies the stated normalization.
Mask PNG files contain uint8 class indices and are never photometrically normalized.
EXIF rotation is not applied without corresponding annotation normalization.

Only genuine, valid, nonduplicate segmentation pairs are exported, after the
quality audit, into a unique `processed/<run>/` directory. Input bytes are checked
again before export. Image/annotation changes invalidate the sample. Box-only
inputs produce no segmentation pairs.

`reports/qci1/` contains:

- `dataset_manifest.json`, `qci1_summary.json`: typed actual counts/status/map.
- `dataset_statistics.json`: splits, shapes, class frequencies and quality issues.
- `samples.csv`, `samples.jsonl`: streamed paired-record metadata.
- `leakage.jsonl`, `orphan_annotations.jsonl`: actual rejected relationships.
- `source_annotation_sanity_grid.png`: real box audit, explicitly not masks.
- `segmentation_sanity_grid.png`: generated only with genuine eligible segmentation.
- `memory_profile.json` and CSV: actual full-workload RSS evidence.
- `QCI_1_Production_Review.md`: acceptance and limitations, including missing truth.

`reports/qci1/segmentation/` holds the acquired source provenance, real-mask
manifest, metadata, genuine overlay grid and measured mask RSS. Initial PARTIAL
duplicate audit is retained in `source_before_dedup/`. Only original textile
boxes lack segmentation truth; the new publisher fine masks provide actual
segmentation evidence. Test fixtures are not substituted for these real masks.

For reproduction in a fresh workspace, `acquire_segmentation --download` is an
explicit online setup command, separate from offline ingestion. It rejects an
existing archive/destination. Run the real-mask CLI once (initial exit3), then
`python -m QCI_1_Surface_Defect_Segmentation.curate_duplicates` to preserve that
audit and quarantine every duplicate copy; rerun the CLI (exit0). The download
is not repeated at runtime. Restore the verified runtime ZIP for fully offline
setup. The provenance CSV in the dataset tracks every original image/mask hash.
Item-ID grouping preserves all views together; accepted splits302/48/16, with
no remaining exact-content duplicate groups or physical-item split leakage.

## Splits, leakage and resource limits

Existing YAML splits are preserved. If no splits exist, the documented fallback
is a seed-42 decoded-content hash assignment to 80/10/10, so identical content
cannot enter different generated splits. Existing splits are not reshuffled.
File SHA256 and canonical decoded-RGB SHA256 (including dimensions) are recorded;
all repeated decoded content is reported and quarantined from segmentation export.
This is an exact-content audit, not a perceptual or source-family leakage guarantee.

Discovery, hashes, records and aggregation use a SQLite disk index with 2 MiB
page cache and file-backed temporary storage. Python holds one decoded sample,
bounded annotations and at most six sanity identities. Limits cover files,
annotation bytes/instances/points, recursion depth, target/source pixels and
visualization capacity. Actual maximum source dimensions are 5184x3888; the
config's 24-million-pixel limit accepts them while rejecting larger inputs before
decoding. No unbounded producer queue or dataset-sized image list is introduced.
Local file operations do not need arbitrary network-style timeout wrappers.

Memory profiling compares complete, identical ordered workload windows after
warming the 64 largest sources, and samples transient RSS at 20 Hz. The original
first/last 50-sample comparison is retained separately because those windows had
different resolution mixes; it exceeded 5% and is not hidden. The final report
contains actual values for source-box and genuine-mask preprocessing. The actual
mask workload drifted 0.332%, peak73.602MiB, across732 evaluations after warm-up. No numeric QCI-1 latency SLA was supplied.

## Local Git delivery

Branch: `feature/sprint2-qci1-surface-defect-segmentation`, based on the integrated
IFE-UI3 branch at `37f9dd64a5bfe2597cd2385896eb3b92c9652f29`. Exactly two local
QCI-1 commits preserve all prior task work. Organization access is revoked:
no GitHub push/PR/merge is performed. The task sync script performs a normal named
branch push once access returns, without rewriting history. Review/approval gates
must still be satisfied before merge.

Verified complete-history bundle and separate runtime/source archive live in
`backups/`, with exact commit IDs, SHA256 hashes and restore checks in the ignored
`delivery_manifest.json`. Neither datasets, prepared pairs, local virtual
environment, scan databases nor credentials are committed.

## Offline recovery

After the two commits, run `python -m QCI_1_Surface_Defect_Segmentation.offline_backup`
with the existing backend interpreter. This verifies the complete-history bundle,
every dataset/runtime archive member hash, real-mask ingestion in a fresh clone,
and the later sync helper against a disposable local bare repository.

The ignored backup directory contains `QCI_1_complete_history.bundle`,
`QCI_1_local_datasets_and_runtime.zip`, and `delivery_manifest.json`. The ZIP
contains original `final_dataset`, acquired publisher ZIP, curated masks,
quarantines and detailed ignored reports/processed pairs. Virtual environments
and credentials are not included. Check the recorded archive SHA256 before use.

Restore to a fresh folder:

```powershell
git clone --branch feature/sprint2-qci1-surface-defect-segmentation QCI_1_complete_history.bundle restored-qci1
Expand-Archive -LiteralPath QCI_1_local_datasets_and_runtime.zip -DestinationPath restored-qci1
git -C restored-qci1 remote set-url origin https://github.com/devlogixtechnology/industirx.git
```

Use existing offline Python dependencies, then run the preprocessing entry with
`configs/kolektor_segmentation.yaml`. To sync after access returns, invoke
`QCI_1_Surface_Defect_Segmentation/sync_when_access_returns.ps1` in that clone.
The helper pushes the named branch normally; no force push or history rewrite.
