# QCI-1 - Surface defect ingestion and segmentation production review

**Implementation and real-mask dataset preparation: PASS.** Ready for local
code/noncommercial dataset review. Full release DoD remains unmet: repository
access/PR, prior repository numerical failures and commercial dataset permission.

## Architecture and repository audit

Branch `feature/sprint2-qci1-surface-defect-segmentation` was created for QCI-1
from integrated IFE-UI3 HEAD `37f9dd64a5bfe2597cd2385896eb3b92c9652f29`. Earlier
tasks are preserved. Separate task folder extends this repository through
`Preprocessing/scripts/prepare_surface_segmentation.py` and reuses the existing
YOLO label validator; this is not a separate project. Existing model/API/UI code
is untouched. `./models/` absent, `Backend/best.pt` present but unused. No trained
segmentation model, weights, accuracy metric or unspecified latency SLA invented.
No GPU/Modal session started. Python3.12.9; installed versions: {'pydantic': '2.12.5', 'Pillow': '12.1.1', 'numpy': '2.4.6', 'opencv-python': '4.13.0.92', 'pytest': '9.1.1', 'PyYAML': '6.0.3', 'psutil': '7.2.2'}.

Discovery -> local pairing -> Pydantic v2 contracts -> bounded decode/validation
-> genuine annotation normalization -> RGB/mask preprocessing -> disk leakage
audit -> eligible exports -> streamed manifest/statistics and actual visuals.

## Original textile corpus, unchanged

Existing notebook identifies `muhammadharisabid/fabricdefectntu`; class mapping
comes from actual `final_dataset/data.yaml`, SHA256 `0a755898f30ed873799a8a8782e6ad835959ce8a5c7e4a4d2b96e0de33270be8`.
4742 images, 4741 source-valid,
1 invalid; original splits preserved: {'train': 3900, 'val': 562, 'test': 280}.
All 6,571 original nonempty label rows are five-field YOLO detection boxes,
not [segmentation polygons](https://docs.ultralytics.com/datasets/segment/).
Genuine segmentation annotations in this original source:0. Its status remains
**BLOCKED**, safely without converting boxes or empty detection labels to masks.

| Source ID | Actual class | Valid samples | Annotation rows | Foreground pixels |
| --- | --- | --- | --- | --- |
| 0 | baekra | 415 | 593 | unavailable |
| 1 | color issues | 201 | 515 | unavailable |
| 2 | contamination | 363 | 410 | unavailable |
| 3 | cut | 660 | 841 | unavailable |
| 4 | gray stitch | 555 | 800 | unavailable |
| 5 | selvet | 530 | 1020 | unavailable |
| 6 | stain | 1649 | 2390 | unavailable |

Rejected source: `images/train/augmented_topbasi-33-_jpg.rf.9c983d8140611025a9d2b16226291459.jpg`:
zero-width class-6 box. Source bytes remain unchanged. Integer-valued class text
such as `4.0` is normalized with exact Decimal checks and recorded warnings.
Corrupt images:0; missing annotations:
0; orphans:0; exact decoded
duplicate groups:0; cross-split groups:0.
Box foreground area/pixels are null, not invented zeros. Existing combined
training ZIP is also box-only; the inspected raw cache is not a valid ZIP.

## Downloaded genuine surface-defect segmentation data

At the user's request, acquired publisher **KolektorSDD fine annotations** from
[ViCoS Lab](https://www.vicos.si/resources/kolektorsdd/), rather than weak box labels.
Original archive:101831129 bytes; SHA256
`65dc621693418585de9c4467d1340ea7958a6181816f0dc2883a1e8b61f9d4dc`. Original publisher ZIP and all masks retained.

Original399 pairs: one (`kos20/Part4_label.bmp`) contains two grayscale85 pixels
besides0/255. Its original image/mask are quarantined without guessing those
pixels. First full audit found16 exact duplicate groups crossing splits; all32
copies are also quarantined. The initial PARTIAL audit and failure/leakage evidence
remain under `segmentation/source_before_dedup/`. Total33 original exclusions.
The provenance CSV records hashes, original paths, assigned item group and
quarantine reasons; no source file or defect geometry is fabricated.

Accepted **366** real pairs: **47 defective**,
**319 genuine background**. Final status **SUCCESS**;
eligible/exported pairs **366**. Source foreground
pixels **154429**. Final issues
{}; orphans0; duplicate groups0;
cross-split duplicates0. All masks match image dimensions.

Publisher classes are binary defect/nondefect: canonical `0:defect`, derived
mask `0=background,1=defect`. This is not relabelled as textile cut/stain or mixed
with the original seven-class map. Images copied byte-for-byte; BMP palette
colors are validated as binary grayscale before exact0/255 ->0/1 normalization.
No image thresholding or model-generated masks. Dataset archive supplies no
train/val/test layout, so seed42 item-ID hash80/10/10 fallback assigns splits
{'train': 302, 'val': 48, 'test': 16}. All photographed parts of a physical item remain together;
group leakage0. Ratios vary with finite item groups. Original textile splits are
not reshuffled. Exact-content audit is not proof of no perceptual leakage.

License **CC BY-NC-SA4.0**: local noncommercial research/review only; commercial
deployment requires [publisher permission](https://www.vicos.si/resources/kolektorsdd/),
which has not been obtained. Cite Tabernik et al., *Segmentation-Based Deep-Learning
Approach for Surface-Defect Detection*, DOI10.1007/s10845-019-01476-x.

## Typed validation, reproducibility and offline contract

Pydantic v2 forbids unknown contract fields; source-valid and segmentation-valid
are separate. Local path resolution rejects URL/UNC/mapped storage, source-root
escapes, symlinks and junctions. Structured fatal/sample issues distinguish bad
config/storage from corrupted image/mask, malformed label, unknown class, missing
or orphan pairs, duplicate IDs, dimension mismatch and changed inputs.
Polygons require three distinct vertices, finite normalized bounds, positive
area and no self intersections. Same-class overlap unions; different-class
overlap rejects. Indexed masks require actual lossless PNG and declared indices.

RGB aspect-preserving640x640 letterbox: area shrink/linear enlarge, padding114;
mask nearest-neighbor with background padding0. Tensor float32 RGB CHW/255;
stored RGB PNG uint8, mask PNG categorical uint8. Source class k maps to mask
k+1 while original IDs remain in metadata. Only genuine valid nonleaking pairs
export after the audit; source hashes are rechecked before export. Masks receive
no photometric normalization. Known SDK image-open hooks are bypassed via verified
native Pillow so corrupt decoding cannot trigger optional package installation.

Acquisition is a separate one-time online setup command. Both subsequent actual
ingestion/profile processes block Python TCP connect/connect_ex: attempted
external connections0; runtime downloads0; storage/model/annotation APIs0.
Processing uses local NTFS. WiFi was not physically disconnected. No GPU credits
were used and no GPU connection needs idle shutdown.

## Bounded memory and measured performance

One sample at a time; disk-backed SQLite paths/hashes/errors with2MiB cache and
file-backed sorts. At most six sanity identities; actual positive masks preferred.
File counts/bytes, source dimensions, annotation instances/points and directory
depth have explicit limits. Textile max5184x3888 fits the audited24-million-pixel
budget; genuine-mask source uses2-million-pixel budget. Output streams to disk.
Two matched complete ordered passes follow64-largest-image warm-up; strict drift
is absolute difference of pass mean RSS / first-pass mean RSS. Transient peak
sampled20Hz. Actual start/mean/end values and per-sample CSVs retained.

| Workload | Evaluations | Stable means MiB | Drift | Peak MiB | <5% |
| --- | --- | --- | --- | --- | --- |
| Existing textile RGB/boxes | 9484 | 71.940 -> 74.240 | 3.197% | 258.980 | True |
| Genuine RGB/indexed masks | 732 | 59.131 -> 59.327 | 0.332% | 73.602 | True |

Initial short textile windows failed at8.555% and remain
in `memory_profile_short_windows.json`/CSV. Complete matching passes avoid
comparing different source-resolution mixes. Raw endpoint deltas differ and
are not claimed<5%; finite tests cannot prove absence of all future leaks.
Actual textile audit:244.550s,
19.391 samples/s. Actual genuine-mask audit:
54.858s,6.672
samples/s, mean scan54.280ms.
No numeric QCI latency SLA supplied, so no SLA pass is invented.

## Tests and proof

Focused pytest: collected74, **74 passed**,
0 failed,0 skipped,0 errors,
8.39s. Covers geometry/rasterization, genuine positive
and negative formats, mask interpolation, corruption, contracts, source fidelity,
grouping/quarantine, duplicates, bounds, mutation and network/SDK isolation.
Normal root `pytest -q`: collected249, **247 passed**,
**2 failed**,0 skipped,0 errors,
98.82s. Remaining failures are unchanged CPU1 artifact
size11.773MB vs6.5MB and AP50 drop1.025pp vs<1pp. No tests/thresholds weakened.
Runtime restore clones excluded; all actual source test modules collected.

Raw focused/root terminal logs, both CLI logs, manifests/statistics/metadata CSVs,
actual source box grid, genuine publisher mask overlays, memory CSV/JSON and
local HTML proof page are retained. `proof_of_work.png` is an actual fresh
headless Edge screenshot of that page, not a fabricated OS-terminal capture.
Synthetic fixtures do not substitute for real segmentation visuals.

## Definition of Done and delivery

| Gate | Result |
| --- | --- |
| Existing architecture, branch, separate task folder | PASS |
| Pydantic v2 typed offline ingestion and safe rejection | PASS |
| Actual repository dataset/map audit | PASS; boxes correctly BLOCKED |
| Genuine segmentation data prepared and visualized | PASS;366 accepted,33 original quarantines |
| Reproducible preprocessing, splits and leakage checks | PASS |
| Bounded RSS, strict matched-pass drift<5% | PASS |
| Focused tests | PASS |
| Complete repository tests | FAIL;2 prior CPU1 numerical gates |
| Docs, proof, exactly two local commits and recovery | PASS |
| GitHub PR | PENDING; revoked organization access |
| Commercial dataset permission | PENDING; research-only data |
| Full release DoD | NOT MET; local implementation reviewable |

Commit author `ehtisham5618 <ehtisham.malik5618@gmail.com>`. Complete-history Git
bundle and independently hashed original/derived dataset/runtime ZIP are in
ignored task `backups/`. Recovery verifies fresh-clone real-mask ingestion and
future push helper against a disposable local bare repo. Later ordinary sync:
`powershell -ExecutionPolicy Bypass -File QCI_1_Surface_Defect_Segmentation/sync_when_access_returns.ps1`.
No GitHub push, PR URL, merge, tag or Slack submission claimed.

Changed: QCI package/config/docs, Preprocessing entry, four root QCI test modules,
pytest config, root README/requirements/.gitignore and actual QCI reports/proof.
No model/tracker/UI or experiment registry changed. Data, masks, ZIPs and virtual
environments stay outside Git. No additional project was created.
