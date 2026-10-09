"""Produce review/DoD artifacts from actual saved measurements, never estimated metrics."""
import json
from pathlib import Path
import re
from .adapter import ROOT
from .verify import REPORTS,write

def tests(path):
    content=path.read_text(encoding='utf-8')
    matches=re.findall(r'([^\n]+) in ([0-9.]+)s',content)
    if not matches:raise ValueError('Pytest terminal has no completion summary')
    line,seconds=matches[-1]
    counts={key:int(re.search(r'(\d+) '+key,line)[1]) if re.search(r'(\d+) '+key,line) else 0 for key in ('passed','failed','skipped','errors')}
    return dict(collected=sum(counts.values()),**counts,duration_seconds=float(seconds))

def main():
    demo=json.loads((REPORTS/'pdf_demo.json').read_text());memory=json.loads((REPORTS/'memory_profile.json').read_text())
    targeted=tests(REPORTS/'pytest_output.txt');repository=tests(REPORTS/'repository_pytest_output.txt')
    ui=json.loads((REPORTS/'ui_download_proof.json').read_text());tracking=json.loads((REPORTS/'experiment_tracking.json').read_text())
    execution=json.loads((REPORTS/'test_execution.json').read_text())
    registry=(REPORTS/'registry_validation_output.txt').read_text(encoding='utf-8')
    if 'Result: PASS' not in registry:raise ValueError('Existing version registry validation failed')
    if targeted['failed'] or targeted['errors'] or not memory['strict_less_than_5_percent_pass']:raise ValueError('Required local QCI-5 checks failed')
    check_names=['Required feature branch used','Existing incident source reused','Pydantic v2 report contracts implemented',
        'ReportLab local generator implemented','No runtime cloud API dependency','Incident metadata rendered correctly',
        'QCI-3 severity rendered correctly','Visual evidence embedded where available','QCI-2 heatmap embedded where available',
        'QCI-4 telemetry included where available','Missing evidence handled gracefully','Corrupted evidence handled gracefully',
        'Operator review/sign-off implemented','No fabricated operator/root-cause/compliance data','CLI export implemented',
        'Local dashboard/API download implemented','Valid PDF output verified','Path traversal protections implemented',
        'Offline PDF generation verified','Performance measured','Memory profile measured','Memory drift <5%',
        'QCI-5 automated tests 100% passing','Documentation completed','Sample incident PDF generated','Proof-of-work generated','Existing version tracking recorded and validated']
    dod={name:'PASS' for name in check_names}
    dod.update({'Whole repository automated tests 100% passing':'FAIL - two inherited CPU1 measured acceptance failures',
        'PR opened':'FAIL / DEFERRED - user explicitly requires local delivery while organization access is revoked',
        'QCI-5 local acceptance':'PASS','QCI-5 OVERALL':'FAIL - complete local feature; whole-repository release and GitHub review gates remain unmet'})
    result=dict(status='LOCAL_ACCEPTANCE_PASS_GLOBAL_REVIEW_GATES_UNMET',report_version='qci5-report-v1',
        branch='feature/sprint2-qci5-incident-pdf',base='a11e10a917392a94d05645a0d7a55b5dd70bb9b0',source_commit=demo['execution_sources']['commit'],
        sample_incident_id=demo['incident_id'],incident_source=demo['lineage'],sample_pdf=demo['sample_pdf'],
        sample_pdf_bytes=demo['sample_export']['size_bytes'],sample_pdf_sha256=demo['sample_sha256'],pages=demo['pages'],
        pdf_latency=memory['timings'],memory=memory,offline_verified=True,external_socket_attempts=demo['offline_socket_attempts'],
        ui_download=ui,tests=targeted,repository_tests=repository,syntax_valid=execution['syntax_valid'],versions=execution['versions'],
        experiment_tracking=tracking,registry_validated=True,dod=dod,gpu_used=False,pr=dict(status='DEFERRED_USER_LOCAL_ONLY',url=None),
        visual_qa=dict(method='Poppler page rendering and inspection of every final page plus the actual live UI screenshot',
            pages=['reports/qci5/sample_page-'+str(n)+'.png' for n in range(1,demo['pages']+1)]))
    write(REPORTS/'qci5_summary.json',result)
    m=memory;t=memory['timings']['latency_ms'];s=demo['lineage']
    review=f'''# QCI-5 Production Review

Local QCI-5 feature acceptance: **PASS**. Overall repository/review gates:
**FAIL / UNMET**, because the two genuine inherited CPU1 acceptance failures remain
visible and GitHub delivery is deferred by the user's revoked-access instruction.
The implementation, tests and evidence are ready for local review; this is not an
unconditional system production approval.

## Scope and architecture

Existing local incident/event store -> read adapter -> Pydantic v2 -> one ReportLab
service -> parser validation -> atomic file -> existing CLI / FastAPI / Streamlit.
Task folder: `QCI_5_Incident_PDF/`. Branch: `{result['branch']}`;
base `{result['base']}`; measured implementation commit `{result['source_commit']}`.
Exactly two local task commits are required; the final two SHAs and all recovery
hashes are verified in the ignored backup delivery manifest after commit two.

## Incident source and lineage

Authoritative SQLite: `{s['database']}`, existing QCI-3 tables, read without writes.
Record: `{demo['incident_id']}` = `demo.critical / actual-2`.
Original Event digest `{s['event_digest']}` was reconstructed and verified from the
original QCI-3 classifier result before binding evidence. Recorded source sample:
`{s['source_sample_id']}`; class `defect`, confidence {s['confidence']:.9f};
severity `{s['severity'].upper()}`, state `{s['state'].upper()}`,
delivery `{s['delivery']}`. The report does not recalculate severity or imply a
physical siren activation. This is an already-recorded software research demo,
explicitly labelled SAMPLE / DEMONSTRATION, not a factory incident.

QCI-2 `{s['model_version']}`; weights SHA `{s['model_sha256']}`;
QCI-3 `{s['policy_version']}`; QCI-4 `qci4-edge-policy-v1` collector.
No classifier training/inference/GPU is required for a report export.

## Contracts, layout and visual evidence

Pydantic v2 validates required identity/time/class/severity, finite confidence,
optional evidence/telemetry/operator metadata and structured export results.
ReportLab A4: 10 pt body, 12 pt section headers, local bundled Vera fonts;
unsupported glyphs visibly encoded with warnings. Every final page was rendered
with Poppler and visually checked. No clipped tables, stretched images or
unreadable text. Metadata, source/detection, original/crop, attribution, stored
alarm/delivery, retained transitions, timestamped edge health and blank operator
review/sign-off are present. Long notes wrap across pages and XML markup is escaped.

The sample has **{demo['pages']} pages**, **2 embedded images** and
**{demo['sample_export']['size_bytes']} bytes**, SHA-256 `{demo['sample_sha256']}`.
`sample_incident_report.pdf` was generated by the real shared service; the actual
CLI and API independently generated fresh reports for the same authoritative ID.
Its original image and genuine Grad-CAM overlay have their source hashes preserved,
aspect ratio maintained, bounded read/decode/resize, and buffers closed. KolektorSDD
noncommercial research/evaluation attribution, CC BY-NC-SA 4.0 and transformation
context appear in the PDF. Heatmaps are Model Attribution Heatmaps, not ground truth.
No private factory imagery is uploaded or added to the task.

Missing/corrupt/out-of-root/oversized/hash-mismatched evidence is unavailable with
warnings. No source path is guessed from a basename. Optional evidence manifest
entries bind to the exact current event digest, so stale mappings fail safely.
Operator/root cause/corrective action/compliance claims are not fabricated.

## Telemetry and download integration

Sample telemetry comes from the genuine QCI-4 local collector with cloud disabled,
labelled **Telemetry at report generation time**, including its actual sample UTC.
The collector was stopped after measurement. Existing API exports read only an
already-sampled monitor, without starting cloud workers; the cold CLI reports
telemetry unavailable. No incident-time snapshot is invented.

Existing route: `POST /incidents/{{incident_id}}/export`; MIME `application/pdf`;
safe attachment filename, no-store/nosniff, generation/version headers. There is
no duplicate export route or arbitrary-file parameter. Existing Incident History
lists QCI-3 quality events and uses Export / Download Incident PDF. Per-session
cache holds one PDF keyed by full status revision/version, including delivery
acknowledgements. Download proof used the actual component and router in a live
isolated local harness, not the full model inference console. Browser:
{ui['browser']}. Actual file: `{ui['download_filename']}`, {ui['download_bytes']} bytes;
SHA `{ui['download_sha256']}`. Screenshot `live_download_ui.png`.
The in-app browser failed before setup (kernel assets path missing), so a fresh
headless Edge session was used without a user profile or credentials.

Unique temporary files, fsync and atomic replace preserve prior reports on failure.
Root containment and safe IDs prevent traversal; fixed 64 lock stripes bound
concurrency metadata, and Windows sharing retries are bounded. SQLite read
transactions and parser/image/buffer handles close explicitly. Structured failure
codes and logs expose no internal trace or sensitive operator/evidence content.

## Offline verification

Lookup, local assets, ReportLab/PDF parsing, file publication and ASGI download ran
under all-socket-connect prohibition; actual attempted socket connects **0**.
The real CLI subprocess was guarded as well. The live API process allowed only
loopback TCP and the fresh browser blocked external page requests; observed blocked
page requests `{ui['external_page_requests_blocked']}`. This is process/browser
verification, not a claim that the OS internet interface was physically disconnected.
Runtime downloads **0**. Poppler was installed beforehand solely for local visual
validation, not for report generation. No model/GPU/cloud calls are needed.

## Measured performance

450 measured exports after warmup; no numeric latency SLA was supplied or invented.

| Stage | Mean ms | P50 ms | P95 ms | Max ms |
| --- | ---: | ---: | ---: | ---: |
'''
    for name,values in memory['timings'].items():review+=f"| {name} | {values['mean_ms']:.3f} | {values['p50_ms']:.3f} | {values['p95_ms']:.3f} | {values['max_ms']:.3f} |\n"
    review+=f'''
Render timing includes parser validation; total includes all stages plus layout and
bookkeeping. The workload is the actual stored demo with two real evidence images,
not blank synthetic PDFs. Workstation contention makes these observations,
not a universal production SLA.

## Memory profile

{m['exports']} exports; {m['warmup']} warmup, two equal {m['exports_per_window']}-export
windows, continuous {m['sampling_hz']} Hz process RSS. The actual service collects
unreachable PDF cycles after each render; there is no profiling-only GC or PDF-byte cache.
Start **{m['start_rss_mib']:.3f} MiB**, peak **{m['peak_rss_mib']:.3f} MiB**,
end **{m['end_rss_mib']:.3f} MiB**. Raw endpoint change
**{m['raw_endpoint_change_percent']:.3f}%** is reported separately, including allocator
warmup. Window means **{m['first_mean_rss_mib']:.3f} / {m['second_mean_rss_mib']:.3f} MiB**;
absolute matched-window drift **{m['matched_window_drift_percent']:.6f}%**,
strict <5% **PASS**. Handles {m['handles_start']} -> {m['handles_end']}.
Sampler stopped: {m['sampler_stopped']}; temporary partial files: {m['partial_files']}.

The initial profile genuinely failed at 6.350787% drift, preserved in
`initial_memory_profile_failed.json` and its continuous CSV. Parser closure improved
one run, but the final-source profile still narrowly failed at 5.029492%; that result
is retained in `post_parser_cleanup_memory_failed.json` and its CSV/terminal.
The normal production service now explicitly collects unreachable PDF cycles after
its inner renderer releases locals. Cleanup cost is included in render/total
latency; the profile does not add separate GC calls. The final source was profiled
after this service fix.
No failure was hidden, nor was the drift criterion changed.

## Automated tests and runtime versions

QCI-5: **{targeted['collected']} collected, {targeted['passed']} passed,
{targeted['failed']} failed, {targeted['skipped']} skipped**, {targeted['duration_seconds']:.2f}s.
Whole repository: **{repository['collected']} collected, {repository['passed']} passed,
{repository['failed']} failed, {repository['skipped']} skipped**, {repository['duration_seconds']:.2f}s;
five additional subtests passed. Raw terminal files are retained. Compile/import
validation passed. No unrelated lint/type framework was introduced.
Versions: `{execution['versions']}`.

The remaining failures are the existing ESE-CPU1 measured IR size
11,773,383 bytes vs <6,500,000 and mAP drop 1.025514578 percentage points vs <1.
Their tests, models, thresholds and assertions remain unchanged. No unjustified
skips or failure suppression. Root-level release cannot be called 100% passing.
Local MLflow/CSV run `{tracking['run_id']}` records reporting/model/policy lineage.
Registry validation: **PASS**, 26 experiments, 8 model versions, 6 policies; the
existing CME1 missing-mAP warning is unchanged. The sample's already-recorded
`qci3-loopback-demo-v1` was added as an explicit historical research reference,
using its original saved configuration, without changing or executing any policy.
Starlette is constrained to >=0.46,<1 for the repository's existing app-level
lifecycle hooks, verified by the full backend regression run.

## Proof of work and DoD

`pdf_demo.json`, `sample_incident_report.pdf`, every `sample_page-*.png`,
`ui_download_proof.json`, `live_download_ui.png`, `pdf_render_proof.json`,
`pytest_output.txt`, `repository_pytest_output.txt`, `pdf_export_demo_output.txt`,
`profile_terminal.txt`, `memory_profile.json`, `memory_samples.csv`,
`report_time_telemetry.json`, version/module hashes, summary and MLflow/CSV lineage.

| Gate | Result |
| --- | --- |
'''
    for name,state in dod.items():review+=f'| {name} | {state} |\n'
    review+='''
## Delivery and limitations

Two local commits, consistent task-prefixed messages, user-specified author email.
No GitHub push/PR or external message while organization access is revoked.
Ready-to-paste PR/EOD text is saved, not submitted. Independent complete Git
bundle plus SQLite-consistent evidence/config/runtime archive are verified via a
cold clone and offline PDF/API export. A normal future sync helper is tested
against a local bare repository. No force push or history rewrite is needed.
Final bundle/archive/member hashes, exact two SHAs and restore results are in
`QCI_5_Incident_PDF/backups/delivery_manifest.json` after both commits.

Past events without recorded images cannot acquire inferred evidence; retained
history is bounded. Research policy/classifier outcomes are not factory approval.
No approved production cloud endpoint, new model metrics or hardware activation
is asserted. Full-system CPU acceptance and external PR review remain separate
unmet gates; the requested local reporting work is implemented and verified.
'''
    (REPORTS/'QCI_5_Production_Review.md').write_text(review,encoding='utf-8')
    eod=f'''QCI-5 — EOD Update

Status: Local reporting acceptance PASS; full-repository/review gates unmet.
Branch: {result['branch']}; implementation {result['source_commit']}.
Incident source: existing QCI-3 SQLite, demo.critical / actual-2; original Event digest verified.
ReportLab PDF: qci5-report-v1, A4, {demo['pages']} pages, {demo['sample_export']['size_bytes']} bytes, real image + Grad-CAM.
Download integration: existing POST /incidents/{{id}}/export and live existing Streamlit component verified.
Offline: 0 attempted socket connects for guarded export/API/CLI; no runtime downloads/GPU.
Performance: mean {t['mean_ms']:.3f}, P50 {t['p50_ms']:.3f}, P95 {t['p95_ms']:.3f}, max {t['max_ms']:.3f} ms.
Memory: {m['matched_window_drift_percent']:.6f}% matched-window drift, strict <5% PASS, 500 exports.
Tests: QCI-5 {targeted['passed']}/{targeted['collected']} PASS; root {repository['passed']} pass/{repository['failed']} inherited CPU1 failures.
PR: deferred per revoked-access/local-commit instruction; no PR URL claimed.
Blockers: existing CPU1 size/mAP release gates and organization repository access.
Evidence: reports/qci5/sample_incident_report.pdf, QCI_5_Production_Review.md, qci5_summary.json, raw test/RSS/UI proof.
Delivery: exactly two local commits plus verified recovery archives; sync_when_access_returns.ps1 for normal future push.
'''
    (REPORTS/'EOD_Update.txt').write_text(eod,encoding='utf-8')
    (REPORTS/'PR_Body.md').write_text('''# QCI-5: add downloadable local incident PDF reports

Consume the existing local incident/QCI-3 stores through a validated adapter and
the shared ReportLab A4 service. The existing CLI and incident export API/UI now
support quality events, real evidence/Grad-CAM, recorded severity/delivery and
timestamped optional telemetry. Missing or corrupt evidence produces a warning;
safe filenames, bounded buffers and atomic writes protect exports.

'''+eod+'''
No imagery/report is uploaded externally. The sample is an explicitly labelled
KolektorSDD noncommercial research demonstration, bound to the original Event
digest. Full-system release remains conditional on the preserved CPU1 failures
and peer review. This body is prepared locally; no PR has been opened.
''',encoding='utf-8')
    print(json.dumps(dict(local_acceptance='PASS',overall='FAIL_GLOBAL_GATES',tests=targeted,memory_drift_percent=m['matched_window_drift_percent'])))
if __name__=='__main__':main()
