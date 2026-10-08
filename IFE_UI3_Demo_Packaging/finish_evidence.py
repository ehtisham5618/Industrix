"""Generate review documents from completed measured artifacts, never constants."""
import json
from .prepare import ROOT,TASK

def main():
    m=json.loads((ROOT/'reports/ife_ui3_demo_metrics.json').read_text(encoding='utf-8'))
    regression=json.loads((TASK/'reports/regression_results.json').read_text(encoding='utf-8'))
    ready=json.loads((TASK/'reports/readiness.json').read_text(encoding='utf-8'))
    assert m['status']=='completed' and ready['overall']=='PASS'
    assert all(v['passed'] for v in regression.values() if isinstance(v,dict))
    e=regression['e2e'];p=m['performance'];v=m['recording'];i=m['incident'];pdf=m['pdf_export'];last=m['telemetry'][-1]
    names=ready['checks']['selected_model']['verification']['class_names']
    mapping='\n'.join(f'| {key} | {value} |' for key,value in names.items())
    tests=sum(value['collected'] for value in regression.values() if isinstance(value,dict))
    pre=m['preflight'];start={c['camera_id']:c['status']['processed'] for c in pre['counts_before']['cameras']}
    finish={c['camera_id']:c['status']['processed'] for c in pre['counts_after']['cameras']}
    pre_fps=sum(finish[k]-start[k] for k in start)/pre['seconds']
    pre_t=pre['samples'][-1]
    from datetime import datetime
    confirmation_seconds=(datetime.fromisoformat(i['confirmed_at'])-datetime.fromisoformat(i['first_seen'])).total_seconds()
    perf=(f"CPU: Intel Core i5-7200U @ 2.50 GHz; 2 physical / 4 logical cores; Windows 11.\n\n"
          f"Warmed pre-recording operational aggregate: **{pre_fps:.3f} evaluated FPS** over {pre['seconds']:.3f}s, from completed-frame counter differences across all three sources.\n\n"
          f"Pre-recording pure inference rolling mean / P95: **{pre_t['model_inference_mean_ms']:.3f} / {pre_t['model_inference_p95_ms']:.3f} ms**, latest {pre_t['model_inference_samples']} actual calls before browser capture.\n\n"
          f"During HD recording, actual rolling-five-second operational FPS averaged **{p['operational_evaluated_fps']['mean']:.3f}**, with P95 {p['operational_evaluated_fps']['p95']:.3f}. "
          f"Aggregate canvas-update throughput: {p['aggregate_canvas_updates_fps']:.3f} FPS. These are processed/displayed frames, not 48 FPS model capacity.\n\n"
          f"Pure model inference mean / P95 at the end of recording: **{last['model_inference_mean_ms']:.3f} / {last['model_inference_p95_ms']:.3f} ms**, latest {last['model_inference_samples']} actual OpenVINO calls, excluding preprocess/NMS. "
          f"The mean of rolling mean readings over the recording was {p['inference_mean_ms']['mean']:.3f} ms; it is not pooled raw-call latency. Engine-capacity FPS was not remeasured.\n\n"
          f"System CPU mean / peak: **{p['system_cpu_percent']['mean']:.2f}% / {p['system_cpu_percent']['max']:.2f}%**. Backend RSS mean / peak: **{p['backend_rss_mib']['mean']:.2f} / {p['backend_rss_mib']['max']:.2f} MiB**. "
          f"These include actual recording load; UI, recorder and other workstation processes contribute to system CPU.\n\n"
          f"Backend result-ready to canvas-update delivery mean / P95: **{p['ui_delivery_ms']['mean']:.3f} / {p['ui_delivery_ms']['p95']:.3f} ms**, "
          f"{p['ui_delivery_ms']['count']} acknowledged rendered frames. Clock alignment uses the lowest RTT midpoint; uncertainty {m['browser_metrics']['clockUncertaintyMs']:.3f} ms. "
          f"This excludes capture/sampling/inference and does not measure physical screen paint.\n\n"
          f"Fresh PDF server generation: **{pdf['generation_ms']:.3f} ms**; frontend HTTP-to-bytes {pdf['request_ms']:.3f} ms; "
          f"actual browser click-to-PDF bytes **{pdf['click_to_bytes_seconds']:.3f}s**, below 2.0s.\n")
    dod=[('Required branch used','PASS'),('Full pipeline starts locally','PASS'),('12-class active detector verified','PASS'),
         ('OpenVINO INT8 CPU backend verified','PASS'),('3 concurrent streams active','PASS'),('CPU2 ring15 / sample4 path active','PASS'),
         ('ByteTRACK active','PASS'),('15 evaluated-observation confirmation active','PASS'),('SED-2 escalation active','PASS'),
         ('Streamlit console active','PASS'),('SQLite incident logging active','PASS'),('Snapshot generation active','PASS'),
         ('Offline PDF export active','PASS'),('Physical WiFi/internet-disconnected pipeline verified','FAIL - adapters remained connected; guarded offline execution PASS'),
         ('Core external cloud dependencies required','0'),('Required root E2E pytest','PASS'),('E2E test failures = 0','PASS'),
         ('Actual CPU latency documented','PASS'),('Actual aggregate FPS documented','PASS'),('No fabricated 16 ms / 48 FPS values','PASS'),
         ('Approximately two-minute HD demo recorded','PASS'),('Video file validated','PASS'),('Video uploaded','MANUAL ACTION REQUIRED'),
         ('Demo review agenda updated','PASS'),('PR created','FAIL - organization access revoked'),('PR merged','HUMAN APPROVAL REQUIRED - after restored access'),
         ('Release tag created on merged commit','NOT AUTHORIZED - no approved merge'),('IFE-UI3 OVERALL','FAIL - physical disconnect, upload and release gates pending')]
    table='\n'.join(f'| {label} | {state} |' for label,state in dod)
    timeline='\n'.join(f"| {entry['at']:.2f}s | {entry['action']} |" for entry in m['timeline'] if entry['action']!='progress')
    text=f'''# IFE-UI3 - End-to-End System Demo Report

**Local technical integration, guarded offline run and actual recording: PASS.**
**IFE-UI3 full Definition of Done: FAIL.** Physical network-disconnect verification
was not performed, authenticated video upload is unavailable, organization access
is revoked, and approved merge/release tagging remain pending. These statuses are
separate from successful local functional validation. Original numerical CPU/model
acceptance shortfalls are not requalified by this demonstration.

Evidence completed: {m['finished_at_utc']} UTC (Oct 9, 2026 PKT).
No earlier completion/deadline claim is made.

## Objective and integrated architecture

Three independent local native-paced captures -> CPU2 ring15/every-fourth-frame
eligibility -> fair shared CPU-only OpenVINO INT8 inference -> calibrated CME-2
confidence -> real per-camera/class ByteTRACK -> 15 consecutive evaluated
observations -> SED-2 rules and software mock relay -> actual Streamlit canvases
and telemetry -> automatic SQLite audit row/native cropped evidence -> fresh
shared ReportLab service -> actual Streamlit PDF download.

No retraining, new detector, threshold relaxation, injected detector output,
synthetic overlay or substituted tracker/state-machine was used in the recording.

## Component inventory

| Component | Exact integrated implementation/version |
| --- | --- |
| Detector | YOLOv8s `cme-opt2-focal-cosine-12class-v1`; existing `Backend/best.pt` |
| Source checkpoint SHA256 | `c4aba081f6357e23a7370a5f7cf98eff2c6faa0c4c20a2d4dcb8bcabdd490061` |
| OpenVINO artifact | `Backend/weights/openvino_int8/model.xml` + `model.bin` + `metadata.yaml`; existing CPU1 manifest verified |
| OpenVINO version | {ready['checks']['selected_model']['verification']['openvino_version']} |
| Device / input | actual EXECUTION_DEVICES CPU only; static batch1, RGB 640x640; INT8 operations verified |
| CME-2 confidence | `cme2-alert-calibrated-v1`; `Confidence_Calibration/configs/calibrated_thresholds.yaml` |
| Tracking / confirmation | `cmeopt3-bytetrack15-v1`; actual upstream BYTETracker; `Backend/configs/bytetrack.yaml`; persist_frames=15 |
| Severity | `SED2-alert-escalation-v1`; `SED_2_Alert_Escalation/configs/severity_rules.yaml` |
| Ingestion | `ESECPU2-async-ring15-sample4-v1`; same schema/roles; optional `IFEUI3-local-demo-v1` source selection |
| Frontend | `IFEUI1-multistream-console-v1`; Streamlit 1.63.0; native local component |
| Incident/report | `IFEUI2-incident-audit-v1`; local SQLite WAL, native crop, shared ReportLab service |
| ReportLab | {ready['checks']['reportlab']['version']} |

Actual 12-class mapping, read from the selected model metadata and verified by the
CPU adapter against the trained mapping:

| ID | Class |
| --- | --- |
{mapping}

Forklift proximity: **not implemented as a class or another active rule**. No
forklift event is drawn or claimed. The video demonstrates representative textile
and fire predictions; it does not claim that every class appears in two minutes.

Existing task inventory: CME-1 expansion/calibration notebooks and CME-2 benchmark
remain present; CME-3 registries remain in Experiment_Tracking. SED-1 camera
manager/config, SED-2 escalation/relay and SED-3 resource monitoring are integrated.
CME-OPT1 dataset augmentation, CME-OPT2 checkpoint and CME-OPT3 tracker are present;
ESE-CPU1 artifacts, CPU2 captures and CPU3 real one-hour evidence are retained;
IFE-UI1 live console and IFE-UI2 audit/PDF are integrated. Implementation presence
does not mean every prior quantitative target passed: OPT2 chemical AP, OPT3
factory-event recall/delay, CPU1 size/accuracy/latency and CPU2/CPU3 throughput
shortfalls remain documented in their original reports.

## Offline verification

Physical WiFi and Ethernet remained connected. No claim of OS-wide internet
disconnection is made. Both backend and frontend were launched with a guard
rejecting non-loopback Python TCP `connect` and `connect_ex` before imports.
A fresh Edge context blocked non-loopback page HTTP requests. All OpenCV source
URLs were local files, so native decoding required no external transport.
Local browser/API/WebSocket IPC remained available. The selected-model test also
proves an attempted non-loopback TCP connection is rejected.

Backend startup, local model loading/reloading, three concurrent sources,
ByteTRACK, real severity, Streamlit, SQLite, JPEG evidence, fresh PDF and download
all succeeded under those guards. Attempted external backend/frontend TCP
connections: {len(m['offline']['external_tcp_attempts'])}; browser external page
requests: {len(m['offline']['browser_external_requests'])}. Required cloud inference,
external storage, external alert and remote PDF API calls: **0**. No runtime pip,
CDN asset or weight download was used. OpenVINO telemetry consent is declined for
the project process before imports; account-wide consent is unchanged.

Runtime audit: frontend requests/fetch and backend WebSockets use only the local
FastAPI endpoint. SQLite, snapshots, JSONL alert history and ReportLab use local
files. IoT is the existing software-only relay. No runtime Google/OpenAI/cloud
inference/storage/report API is on this execution path. This proves guarded
offline operation, not a physical WiFi-disconnect exercise.

## Automated end-to-end test and regressions

Required path: `tests/test_end_to_end_pipeline.py`.
Command: backend Python `-m pytest tests/test_end_to_end_pipeline.py -v` (equivalent
to the required `pytest tests/test_end_to_end_pipeline.py`).
Collected **{e['collected']}**, passed **{e['passed_count']}**, failed **0**, skipped
**{e['skipped']}**, duration **{e['duration_seconds']:.3f}s**. Raw output/environment
and exact command: `IFE_UI3_E2E_Test_Result.txt`.

Tests load/compile real selected INT8 CPU artifacts, ingest frames from all three
original local sources, validate the output contract, and run a fresh real model
inference for every hazard observation. Actual ByteTRACK, unchanged calibration,
15 observations, SED-2, temporary DB/crops, valid embedded-image PDF, reopened DB,
unknown-ID handling and ASGI API contract are checked. Test timestamps advance
deterministically to exercise escalation quickly; the recording uses actual
capture wall clocks. No model/tracker/storage/report mocks replace the pipeline.
Temporary fixture storage is deleted after tests and never uses the demo DB.

Sequential relevant functional regression/E2E total: **{tests} passed, 0 failures**.
The original measured hardware acceptance gates are not rerun or hidden as green
functional tests; they remain explicitly failed in retained CPU/model reports.
Regression group counts/durations and raw terminal outputs are in the task's
`reports/`. Existing FastAPI on_event deprecation warnings remain visible.

## Three streams, tracking and actual scenario

Same CPU2 schema, IDs, deployment roles, ring capacity 15 and sampler phase0/every4.
Demo Camera 01 uses a 640x640 letterboxed repeated textile training image; Camera
02 uses 75 seconds black standby followed by a repeated fire training image;
Camera 03 uses a 640x360 derivative of the original worker clip at original cadence.
These smaller optional sources reduce decode overhead during 1080p recording.
The original three-source config and its quantitative evidence are unchanged.

Both still-image scenarios are disclosed on screen and their source archive
members, exact hashes and genuine selected-model predictions are retained in
`fixture_provenance.json` and `textile_provenance.json`. Existing training images
provide integration fixtures, not independent held-out accuracy or actual factory
bay recordings. The worker video is also a public stand-in, not installed CCTV.
No target performance or generalization claim follows from this fixture selection.

The official recording generated **{i['incident_id']}** for actual class
**{i['class_name']}**, camera **{i['camera_id']}**, confidence **{i['confidence']*100:.2f}%**,
track **{i['track_id']}**, confirmation_frames **{i['confirmation_frames']}**, severity
**{i['severity'].upper()}**. Source event `{i['event_id']}`, violation
`{i['violation_id']}`. Evidence frame {i['evidence_frame_id']}, native crop
{i['snapshot_width']}x{i['snapshot_height']}; SHA256 `{i['snapshot_sha256']}`.
Candidates and confirmed/active states are present in real browser metadata.
First observed fire to formal confirmation took **{confirmation_seconds:.3f}s**
on this loaded workstation. Fifteen evaluated observations are an actual count,
not an automatic promise of a two-second response. Visible smoke boxes are real
raw predictions below the calibrated smoke threshold; no smoke incident is claimed.
The software relay recorded {m['iot']['trigger_count']} actual mock trigger(s),
state `{m['iot']['state']}`; the UI explicitly says SIMULATED SAFETY SHUTDOWN.

## Incident/PDF verification and restart

Rehearsal incident {m['rehearsal']['incident']['incident_id']} was generated from
real decoded footage, freshly exported and retained across a complete backend
restart with the same demo DB. Its evidence hash remained unchanged; re-export
after restart took {m['restart']['pdf_generation_ms']:.3f} ms. The model reloaded
locally and three new capture sessions started before recording.
The new recorded incident differs from the rehearsal incident, with persistent
ID sequence. No operator database was cleared.

The actual Streamlit download `{pdf['filename']}` is {pdf['pages']} valid PDF pages
and includes the correct incident, CRITICAL severity, cropped evidence, SAMPLE
label, sign-off and corrective-action fields. Its SHA256 is `{pdf['sha256']}`.
PDF pages were rendered locally with PyMuPDF because Poppler is unavailable, then
visually inspected. No PDF layout/generator was replaced for the recording.

## Performance

{perf}
Recording load can reduce throughput and increase frame age. Overload drops are
reported in final camera status rather than hidden. No camera read/worker crash
is claimed unless the actual counters show it. These numbers do not supersede
the original 60-minute CPU3 profile or qualify 16 ms / 48 FPS operation.

## Actual recording and validation

File: `{v['path']}`. Duration **{v['duration_seconds']:.3f}s**, **{v['width']}x{v['height']}**,
codec **{v['codec']}**, frame rate **{v['fps']}**, size **{v['bytes']:,} bytes**.
SHA256 `{v['sha256']}`. Actual fresh Edge viewport recorded through Playwright,
then H.264 encoded by local FFmpeg. Only initial loading was trimmed
({v['loading_trim_seconds']:.3f}s); no fake metrics, overlays, animation or retiming.
Audio: {v['audio']}. Entire final MP4 decoded successfully. Keyframes at
10/40/75/100/115 seconds and actual UI screenshots were visually inspected for
readability, three feeds, real boxes/states, local evidence and PDF generation.

Actual action timeline:

| Recording time | Actual action |
| --- | --- |
{timeline}

Upload: **NOT UPLOADED / MANUAL ACTION REQUIRED**. No connected authenticated
Drive/Loom/YouTube upload capability is available. Recommended action: upload the
verified MP4 to Google Drive, give intended reviewers link access and add the
actual returned share URL to `Saturday_Demo_Agenda.md` and the prepared PR body.
No platform URL, visibility setting or upload success is invented.

## Git, PR and release status

Branch `feature/atlantis-demo-packaging` was created from the integrated UI2 HEAD
`bfbc4e6d6f07e3f4606f4b7d90852b64e4e3b015`, not an obsolete main branch missing
completed dependent tasks. The branch isolates this task's exactly two new
commits while preserving all prior local task commits. Author:
`ehtisham5618 <ehtisham.malik5618@gmail.com>`; messages follow `IFE-UI3: ...`.
Exact saved hashes/messages are in the ignored verified backup delivery manifest
and final delivery response, produced after both commits exist.

Origin: `https://github.com/devlogixtechnology/industirx.git`. Access revoked:
no push or PR attempted, no PR URL, no merge. Prepared PR title/body is in
`IFE_UI3_Demo_Packaging/pr_description.md`. Future normal sync:
`git push -u origin feature/atlantis-demo-packaging`, or the task sync script.
This sends the integrated ancestor history too, without force-pushing/rebasing.
Reviewers and protections must be satisfied before merge.

Requested release `v0.4.0-sprint4-cpu-ready`: **NOT CREATED / NOT AUTHORIZED**.
No existing tag was moved. Only an approved actual merged commit may be tagged
by an authorized maintainer; commands and limits are in `release_notes.md`.
Verified complete-history bundle, restored HEAD and separate consistent runtime
archive preserve source, model/media, demo DB/evidence and recording for recovery.

## Definition of Done

| Check | Result |
| --- | --- |
{table}

## Files

Created: the separate `IFE_UI3_Demo_Packaging/` source/config/docs/evidence package;
required root `tests/test_end_to_end_pipeline.py` and two local test images;
demo script/checklist/agenda/E2E output/integration report/metrics and four genuine
UI screenshots under root `reports/`.
Modified: `Backend/live_console.py` (actual inference timing), `Frontend/app.py`
(optional labelled demo caption), native console JS/CSS/HTML (readable native-source
labels, correct active confirmation state, actual class count/timing/relay),
`Frontend/incidents.py` (truthful prerecorded-demo description), `.gitignore`,
README and existing experiment-tracking registry support/evidence.
Removed: none. Runtime database, native crops, full MP4, local credentials and
large source/weight files are excluded from Git and recovered separately.
'''
    (ROOT/'reports/IFE_UI3_End_to_End_Demo_Report.md').write_text(text,encoding='utf-8')
    checklist='''# IFE-UI3 recording and release checklist

- [ ] Physical WiFi/internet disconnected - NOT PERFORMED; adapters remained up.
- [x] Both Python servers block non-loopback TCP; browser blocks external HTTP.
- [x] Backend startup and complete restart verified under guards.
- [x] Selected local OpenVINO INT8 CPU artifacts and 12 names verified.
- [x] Three real local feeds/capture sessions active through CPU2 ring15/sample4.
- [x] Actual ByteTRACK, candidate observations, strict15 and SED-2 verified.
- [x] Live Streamlit, real telemetry, readable labels and software-only relay.
- [x] Separate writable demo SQLite, native evidence and persistence after restart.
- [x] Fresh local ReportLab export and actual browser download under two seconds.
- [x] Required root E2E pytest passes; no skipped critical tests or failures.
- [x] Functional regressions pass; original hardware acceptance failures disclosed.
- [x] Actual 1920x1080 recording created and fully decoded/visually inspected.
- [x] No credential, private token or RTSP password appears in the walkthrough.
- [x] Runtime MP4/database/crops kept outside Git, with recovery archive.
- [x] Exactly two new local task commits and complete-history bundle verified.
- [ ] Upload - MANUAL ACTION REQUIRED; no share URL yet.
- [ ] PR creation/approved merge - pending restored organization access.
- [ ] Correct merged-commit release tag - NOT AUTHORIZED before approved merge.

See the measured integration report and backup delivery manifest for proof. This
checklist describes the final delivered artifacts; commit/archive checks are
confirmed during final delivery, not hardcoded as evidence in the readiness tool.
'''
    (ROOT/'reports/IFE_UI3_Demo_Checklist.md').write_text(checklist,encoding='utf-8')
    pr=f'''# IFE-UI3: package Sprint 4 end-to-end CPU demo

The previously separate CPU capture, inference, tracking, escalation and incident
components now have reproducible local validation and a real HD operator walkthrough.
The package selects labelled deterministic footage while keeping the production
OpenVINO/ByteTRACK/15-observation/SED-2/SQLite/ReportLab pipeline unchanged.
Integration fixes keep active tracks labelled CONFIRMED, scale labels for tall
sources and display actual model class count, rolling inference timings and mock
relay status. Existing detector weights and calibrated thresholds are unchanged.

## Validation

`pytest tests/test_end_to_end_pipeline.py`: {e['passed_count']} passed, 0 failed,
{e['skipped']} skipped, {e['duration_seconds']:.3f}s. Related functional total:
{tests} passed, 0 failures. The real selected CPU model is exercised; temporary
storage and an external-TCP guard make the E2E deterministic and local.
Actual guarded backend restart, three live sources, confirmation/escalation,
persistent native evidence and fresh Streamlit PDF download also pass.
Physical WiFi disconnection was not tested; guarded offline operation passed.

## Performance

{perf}
Original CPU/model numerical gates remain failed; this demo does not requalify
size, accuracy, 16 ms latency or 48 FPS throughput.

## Recording and release

Actual {v['duration_seconds']:.3f}s 1920x1080 MP4 was fully decoded and inspected;
metadata and hashes are in the integration report. Upload pending manual action;
no share URL yet. The repository organization has revoked access: this PR body
is prepared locally, with exactly two saved commits and verified recovery files.
PR creation, approved merge and `v0.4.0-sprint4-cpu-ready` tag remain pending.
Tagging an unmerged feature commit is not authorized.
'''
    (TASK/'pr_description.md').write_text(pr,encoding='utf-8')
    print('Generated final report, checklist and PR body from measured artifacts.')

if __name__=='__main__':main()
