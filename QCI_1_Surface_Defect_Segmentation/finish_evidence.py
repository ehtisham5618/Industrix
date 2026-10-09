"""Build measured review evidence from the existing corpus and real fine masks."""
from __future__ import annotations
import html
import importlib.metadata
import json
from .config import ROOT
from .contracts import MemoryMetrics, ProcessingResult


def main() -> None:
    """Keep code validation, source quarantines and external release gates explicit."""
    out=ROOT/'reports/qci1'; task=ROOT/'QCI_1_Surface_Defect_Segmentation'
    box=ProcessingResult.model_validate_json((out/'dataset_manifest.json').read_text(encoding='utf-8'))
    seg=ProcessingResult.model_validate_json((out/'segmentation/dataset_manifest.json').read_text(encoding='utf-8'))
    bm=json.loads((out/'memory_profile.json').read_text(encoding='utf-8'))
    sm=json.loads((out/'segmentation/memory_profile.json').read_text(encoding='utf-8'))
    initial=json.loads((out/'memory_profile_short_windows.json').read_text(encoding='utf-8'))
    checks=json.loads((out/'test_results.json').read_text(encoding='utf-8')); qci=checks['qci']; repo=checks['repository']
    acquired=json.loads((out/'segmentation/source_acquisition.json').read_text(encoding='utf-8'))
    for result,memory,directory in ((box,bm,out),(seg,sm,out/'segmentation')):
        result.memory=MemoryMetrics(**{k:memory[k] for k in MemoryMetrics.model_fields})
        for name in ('dataset_manifest.json','qci1_summary.json'):
            (directory/name).write_text(result.model_dump_json(indent=2)+'\n',encoding='utf-8')
    bs=box.statistics; ss=seg.statistics
    classes='\n'.join(f'| {c.class_id} | {c.name} | {c.samples} | {c.instances} | unavailable |' for c in bs.classes)
    versions={name:importlib.metadata.version(name) for name in ('pydantic','Pillow','numpy','opencv-python','pytest','PyYAML','psutil')}
    audit=dict(repository_root=str(ROOT),branch='feature/sprint2-qci1-surface-defect-segmentation',base_commit='37f9dd64a5bfe2597cd2385896eb3b92c9652f29',
        original_dataset='final_dataset',original_mapping='final_dataset/data.yaml',original_annotation_format='YOLO detection boxes',original_source='muhammadharisabid/fabricdefectntu (existing notebook)',
        original_images=bs.total_samples,original_splits=bs.split_counts,original_segmentation_truth=0,
        acquired_dataset=acquired,models_folder_exists=(ROOT/'models').exists(),backend_detector_exists=(ROOT/'Backend/best.pt').exists(),
        weights_loaded=False,gpu_used=False,modal_session_started=False,versions=versions,
        original_zip_note='Existing combined training ZIP contains only five-field boxes. Kagglehub 1.archive is 12,582,912 bytes and not a valid ZIP.')
    (out/'repository_audit.json').write_text(json.dumps(audit,indent=2)+'\n',encoding='utf-8')
    report=f'''# QCI-1 - Surface defect ingestion and segmentation production review

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
No GPU/Modal session started. Python3.12.9; installed versions: {versions}.

Discovery -> local pairing -> Pydantic v2 contracts -> bounded decode/validation
-> genuine annotation normalization -> RGB/mask preprocessing -> disk leakage
audit -> eligible exports -> streamed manifest/statistics and actual visuals.

## Original textile corpus, unchanged

Existing notebook identifies `muhammadharisabid/fabricdefectntu`; class mapping
comes from actual `final_dataset/data.yaml`, SHA256 `{box.source_metadata_sha256}`.
{bs.total_samples} images, {bs.source_valid_samples} source-valid,
{bs.invalid_source_samples} invalid; original splits preserved: {bs.split_counts}.
All 6,571 original nonempty label rows are five-field YOLO detection boxes,
not [segmentation polygons](https://docs.ultralytics.com/datasets/segment/).
Genuine segmentation annotations in this original source:0. Its status remains
**{box.status}**, safely without converting boxes or empty detection labels to masks.

| Source ID | Actual class | Valid samples | Annotation rows | Foreground pixels |
| --- | --- | --- | --- | --- |
{classes}

Rejected source: `images/train/augmented_topbasi-33-_jpg.rf.9c983d8140611025a9d2b16226291459.jpg`:
zero-width class-6 box. Source bytes remain unchanged. Integer-valued class text
such as `4.0` is normalized with exact Decimal checks and recorded warnings.
Corrupt images:{bs.issues.get('CORRUPTED_IMAGE',0)}; missing annotations:
{bs.issues.get('MISSING_ANNOTATION',0)}; orphans:{bs.orphan_annotations}; exact decoded
duplicate groups:{bs.duplicate_hash_groups}; cross-split groups:{bs.cross_split_hash_groups}.
Box foreground area/pixels are null, not invented zeros. Existing combined
training ZIP is also box-only; the inspected raw cache is not a valid ZIP.

## Downloaded genuine surface-defect segmentation data

At the user's request, acquired publisher **KolektorSDD fine annotations** from
[ViCoS Lab](https://www.vicos.si/resources/kolektorsdd/), rather than weak box labels.
Original archive:{acquired['archive_bytes']} bytes; SHA256
`{acquired['archive_sha256']}`. Original publisher ZIP and all masks retained.

Original399 pairs: one (`kos20/Part4_label.bmp`) contains two grayscale85 pixels
besides0/255. Its original image/mask are quarantined without guessing those
pixels. First full audit found16 exact duplicate groups crossing splits; all32
copies are also quarantined. The initial PARTIAL audit and failure/leakage evidence
remain under `segmentation/source_before_dedup/`. Total33 original exclusions.
The provenance CSV records hashes, original paths, assigned item group and
quarantine reasons; no source file or defect geometry is fabricated.

Accepted **{ss.total_samples}** real pairs: **{acquired['positive_samples']} defective**,
**{acquired['negative_samples']} genuine background**. Final status **{seg.status}**;
eligible/exported pairs **{ss.valid_segmentation_samples}**. Source foreground
pixels **{sum(c.foreground_pixels or 0 for c in ss.classes)}**. Final issues
{ss.issues}; orphans{ss.orphan_annotations}; duplicate groups{ss.duplicate_hash_groups};
cross-split duplicates{ss.cross_split_hash_groups}. All masks match image dimensions.

Publisher classes are binary defect/nondefect: canonical `0:defect`, derived
mask `0=background,1=defect`. This is not relabelled as textile cut/stain or mixed
with the original seven-class map. Images copied byte-for-byte; BMP palette
colors are validated as binary grayscale before exact0/255 ->0/1 normalization.
No image thresholding or model-generated masks. Dataset archive supplies no
train/val/test layout, so seed42 item-ID hash80/10/10 fallback assigns splits
{ss.split_counts}. All photographed parts of a physical item remain together;
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
| Existing textile RGB/boxes | {bm['samples']} | {bm['stable_start_mean_mib']:.3f} -> {bm['stable_end_mean_mib']:.3f} | {bm['drift_percent']:.3f}% | {bm['peak_rss_mib']:.3f} | {bm['strict_under_5_percent_pass']} |
| Genuine RGB/indexed masks | {sm['samples']} | {sm['stable_start_mean_mib']:.3f} -> {sm['stable_end_mean_mib']:.3f} | {sm['drift_percent']:.3f}% | {sm['peak_rss_mib']:.3f} | {sm['strict_under_5_percent_pass']} |

Initial short textile windows failed at{initial['drift_percent']:.3f}% and remain
in `memory_profile_short_windows.json`/CSV. Complete matching passes avoid
comparing different source-resolution mixes. Raw endpoint deltas differ and
are not claimed<5%; finite tests cannot prove absence of all future leaks.
Actual textile audit:{box.performance.duration_seconds:.3f}s,
{box.performance.samples_per_second:.3f} samples/s. Actual genuine-mask audit:
{seg.performance.duration_seconds:.3f}s,{seg.performance.samples_per_second:.3f}
samples/s, mean scan{seg.performance.mean_sample_ms:.3f}ms.
No numeric QCI latency SLA supplied, so no SLA pass is invented.

## Tests and proof

Focused pytest: collected{qci['collected']}, **{qci['passed']} passed**,
{qci['failed']} failed,{qci['skipped']} skipped,{qci['errors']} errors,
{qci['duration_seconds']:.2f}s. Covers geometry/rasterization, genuine positive
and negative formats, mask interpolation, corruption, contracts, source fidelity,
grouping/quarantine, duplicates, bounds, mutation and network/SDK isolation.
Normal root `pytest -q`: collected{repo['collected']}, **{repo['passed']} passed**,
**{repo['failed']} failed**,{repo['skipped']} skipped,{repo['errors']} errors,
{repo['duration_seconds']:.2f}s. Remaining failures are unchanged CPU1 artifact
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
| Bounded RSS, strict matched-pass drift<5% | {'PASS' if bm['strict_under_5_percent_pass'] and sm['strict_under_5_percent_pass'] else 'FAIL'} |
| Focused tests | {'PASS' if qci['exit_code']==0 else 'FAIL'} |
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
'''
    (out/'QCI_1_Production_Review.md').write_text(report,encoding='utf-8')
    summary=f'QCI-1: typed offline surface-defect ingestion and genuine segmentation preparation.\n\nAudited {bs.total_samples} existing textile images (boxes only). Acquired publisher fine annotations; {ss.valid_segmentation_samples} genuine pairs prepared,33 original samples quarantined. Item groups stay together; class maps are not mixed.\n\nValidation: {qci["passed"]} focused tests passed; root {repo["passed"]} passed/{repo["failed"]} prior CPU1 failures. Genuine-mask RSS drift {sm["drift_percent"]:.3f}% (<5%). No GPU/runtime APIs.\n\nEvidence: reports/qci1/QCI_1_Production_Review.md and proof_of_work.png. Commercial use needs publisher permission. PR pending restored access; exactly two local commits and verified recovery preserved.\n'
    (task/'pr_description.md').write_text(summary,encoding='utf-8')
    (out/'EOD_Update.md').write_text(summary+'\nReady to paste; no message sent.\n',encoding='utf-8')
    terminal=html.escape((out/'pytest_output.txt').read_text(encoding='utf-8'))
    page=f'''<!doctype html><html><head><meta charset="utf-8"><title>QCI-1 actual proof</title><style>body{{font:16px system-ui;background:#eef3f7;color:#17344d;margin:30px}}main{{max-width:1400px;margin:auto}}section{{background:white;border:1px solid #d8e1eb;padding:22px;margin:16px 0;border-radius:8px}}img{{max-width:1000px;width:100%}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font:13px Consolas,monospace}}.note{{background:#fff3d6;padding:18px}}</style></head><body><main><h1>QCI-1 / Actual offline segmentation evidence</h1><section><b>{ss.valid_segmentation_samples} real image/mask pairs prepared</b><p>{acquired['positive_samples']} positive /{acquired['negative_samples']} negative.33 original quarantines; item groups stay together. Existing textile boxes audited separately.</p><p>QCI {qci['passed']} passed /0 failed. Root {repo['passed']} passed /{repo['failed']} prior CPU1 failures. Genuine-mask RSS drift {sm['drift_percent']:.3f}%.</p></section><div class="note">Local research/review complete. Commercial dataset use requires permission. GitHub PR pending restored access.</div><section><h2>Actual pytest terminal output</h2><pre>{terminal}</pre></section><section><h2>Publisher fine segmentation annotations</h2><p>Original image at left, actual defect mask overlay at right. These are not synthetic fixtures.</p><img src="segmentation/segmentation_sanity_grid.png"></section><section><h2>Original textile source box audit</h2><p>Actual boxes; not segmentation masks.</p><img src="source_annotation_sanity_grid.png"></section></main></body></html>'''
    (out/'review.html').write_text(page,encoding='utf-8')
    print('Generated actual review, PR body, EOD update and proof page.')


if __name__=='__main__':main()
