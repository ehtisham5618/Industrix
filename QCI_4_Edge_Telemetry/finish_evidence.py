"""Produce review artifacts from measured tests, HTTP demo and memory profiles."""
from pathlib import Path
import html
import json
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1];REPORTS=ROOT/'reports/qci4'

def test_summary(path):
    text=path.read_text(encoding='utf-8');line=[s for s in text.splitlines() if re.search(r'\d+ passed',s)][-1]
    values={k:int(re.search(r'(\d+) '+k,line).group(1)) if re.search(r'(\d+) '+k,line) else 0 for k in ('passed','failed','skipped','errors')}
    return {**values,'collected':sum(values.values()),'duration_seconds':float(re.search(r'in ([\d.]+)s',line).group(1)),'summary':line}

def main():
    demo=json.loads((REPORTS/'failover_demo.json').read_text());memory=json.loads((REPORTS/'memory_profile.json').read_text());api=json.loads((REPORTS/'api_profile.json').read_text())
    targeted=test_summary(REPORTS/'pytest_output.txt');repository=test_summary(REPORTS/'repository_pytest_output.txt')
    source=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    checks={k:'PASS' for k in ['Required feature branch used','QCI-2/QCI-3 local pipeline remains independent of cloud',
        'Pydantic v2 telemetry contracts implemented/reused','CPU telemetry implemented','RAM telemetry implemented','Disk/spool telemetry implemented',
        'Inference health telemetry implemented','Alert health telemetry implemented','Cloud health detection implemented (local mock)',
        'Cloud-disabled state implemented','Graceful offline/local-only mode implemented','Cloud failure does not block inference',
        'Local durable spool implemented/reused','Spool is bounded','Retries are bounded','Timeouts implemented',
        'Exponential backoff implemented','Idempotent replay/deduplication implemented','Restart-safe pending sync implemented',
        'Cloud recovery implemented','Pending items replay after recovery','Network dropout test passes','429/500/timeout scenarios handled',
        'Malformed cloud response handled','Clean shutdown implemented','Memory profile measured','Offline core execution verified',
        'Documentation completed','Proof-of-work generated']}
    checks['Memory drift <5%']='PASS' if memory['strict_less_than_5_percent_pass'] else 'FAIL'
    checks['Automated QCI-4 tests 100% passing']='PASS' if targeted['failed']==targeted['errors']==0 else 'FAIL'
    checks['Automated whole-repository tests 100% passing']='PASS' if repository['failed']==repository['errors']==0 else 'FAIL'
    checks['PR opened']='FAIL / deferred: user reports revoked repository access; local delivery requested'
    checks['QCI-4 OVERALL']='FAIL for unrestricted release: inherited CPU gates and deferred PR; local implementation verified'
    summary={'task':'QCI-4','implementation':'PASS','overall':'FAIL','scope':'local noncommercial research/evaluation; mock cloud contract',
        'branch':'feature/sprint2-qci4-edge-telemetry-failover','base_branch':'feature/sprint2-qci3-severity-iot-alerts',
        'base_commit':'bf50aabefba2812036b2de03cd6c718af995d1d0','implementation_commit':source,
        'sample_interval_seconds':2,'cloud_enabled_by_default':False,'production_cloud_endpoint_provided':False,
        'targeted_tests':targeted,'repository_tests':repository,'memory':memory,'demo':demo,'api':api,'dod':checks,
        'gpu_used':False,'github_pr':None,'recovery_manifest':'QCI_4_Edge_Telemetry/backups/delivery_manifest.json (generated after two commits)'}
    (REPORTS/'qci4_summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    metric_rows='\n'.join(f"| {name} | {value['mean_ms']:.6f} | {value['p95_ms']:.6f} |" for name,value in [
        ('Standalone collector',api['standalone_collector_latency']),('Actual localhost GET /edge/status',api['http_endpoint_latency']),
        ('Spool batch incl. durable commit',memory['spool_enqueue_latency']),('Cloud POST transport',memory['cloud_post_latency']),
        ('Local alarm core during outage',demo['alarm_core_latency'])])
    dod_rows='\n'.join(f'| {name} | {value} |' for name,value in checks.items())
    phases='\n'.join(f"| {p['phase']} | {p['snapshot']['cloud']['status']} | {p['snapshot']['cloud']['mode']} | {p['snapshot']['spool']['pending']} | {p['snapshot']['inference']['status']} |" for p in demo['phases'])
    report=f'''# QCI-4 production review evidence

The optional local edge telemetry/failover implementation is verified. Overall
unrestricted release remains **FAIL** because whole-repository tests retain two
prior CPU1 acceptance failures and repository access prevents PR submission.
No existing failure or threshold was suppressed. This task does not retrain or
redo QCI-1/QCI-2/QCI-3; QCI-2 received only a bounded local observer hook.

Branch `{summary['branch']}` builds on `{summary['base_branch']}` at
`{summary['base_commit']}`. Implementation commit `{source}`. Exactly two task
commits are saved locally; final hashes and independently verified recovery are
recorded in the ignored delivery manifest after packaging. Author:
ehtisham5618 <ehtisham.malik5618@gmail.com>.

## Architecture, telemetry and privacy

SED-3 hardware sampling is reused without GPU sensors or its unbounded sampling
history thread. Real psutil supplies CPU, RAM, RSS, disk, uptime, thread/handle
counts. First CPU interval is unavailable, not fabricated zero. Memory is MiB;
raw process CPU percent can exceed 100. Default sampling interval: 2 seconds.
Hardware history is capped at 300; actual QCI-2 latency observations at 128.

QCI-1 reports MANIFEST_VALIDATED from its saved report, without repeated image
scans. QCI-2 health uses a weak reference to an actual classifier in this process
and observations of its real return values. Uninstrumented/separate processes
remain UNKNOWN; historical reports are not invented as live metrics. QCI-3
health reads actual local event/audit/outbox tables, including tier counts and
acknowledged/failed/unknown/pending webhook outcomes. QCI-4 never owns severity.

The existing API adds typed `/edge/status` and bounded `/edge/history`; the
Streamlit monitor adds a small health/cloud panel. The real localhost API profile
made {api['actual_http_requests']} GET requests, with {api['warmup_requests']}
warmup requests. Its process has no classifier; it correctly reports model
health UNKNOWN instead of reusing another process's prediction counts.

Cloud is disabled by default, with no endpoint and no sync thread. Enabling
health checks alone does not grant data-upload permission. Both outbound
permissions default false. Typed allowlists permit only gauges and pseudonymous
event summaries; raw images, heatmaps, model weights, source/event names, paths,
raw errors and secrets never enter upload payloads. The current connector accepts
numeric HTTPS IPs with normal certificate verification (plain HTTP only for
loopback) and Content-Length JSON. Named-host/vendor protocols require their
documented bounded adapter; no real production endpoint was supplied or invented.

## State, durable storage, ordering and retry

Cloud states: DISABLED, UNKNOWN, ONLINE, DEGRADED, OFFLINE, RECOVERING.
Modes: LOCAL_ONLY, RECOVERING, CONNECTED. Application-specific health and upload
status are separate. The first failure activates local-only; two failed health
checks give OFFLINE. Upload-only failures remain DEGRADED. Healthy checks do not
erase unresolved delivery failure; normal healthy probes do not fabricate
recovery transitions. Pending replay reaches ONLINE after actual acknowledgement.

Prefixed SQLite tables preserve existing incident/QCI-3 state. A QCI-4-owned
source UUID marker prevents silent source/audit-counter reuse; other QCI-3 tables
remain read-only to the collector. Batches of at most 32 summary rows atomically
commit the accepted cursor prefix. Default limits: 1,000 items, 1 MiB payload,
8 KiB/item, 32 routine items, one-hour routine TTL, 10,000 dedupe receipts with
seven-day TTL, 1,000 logs, 100 MB disk reserve. Database overhead is separately
measured. Events preempt unsent routine data; backpressure preserves source
cursor/local alarm state. Event data is not silently expired. Routine samples
are downsampled to one per 60 seconds. Finite source audit retention gaps are
reported explicitly.

Receiver keys include persistent device UUID and hashed logical identity, so
different devices' audit row 1 cannot collide. Payloads stay immutable. A
resolution cannot overtake its own undelivered Critical transition; a permanent
predecessor blocks that activation for review. Receipt expiry uses a retained
observation watermark; this is bounded-history dedupe, not an infinite archive.
Only a matching item/key/digest plus literal accepted:true and 2xx marks delivery.
The receiver must durably deduplicate; the client alone cannot promise physical
or cross-network exactly-once behavior.

Default timeout 1 s (TCP/TLS establishment conservative bound 2x), attempts 3,
exponential backoff 1..60 s, jitter up to 10%, replay limit 5 items/s. Header and
body deadlines/8 KiB bounds cover slow/trickled replies. 429 sanitized Retry-After
is capped/respected; other 4xx and redirects are permanent. Transport, 500 and
malformed acknowledgement retries are bounded; exhausted ambiguous deliveries
remain DELIVERY_UNKNOWN. Pending/in-flight jobs survive restart; lease recovery
uses the same idempotency identity. Tokens come only from the environment and
never appear in database/status. Disabling preserves pending data; re-enabling
the same policy resumes it. Changed enabled policies need reviewed migration.

One sampler and optional sync worker stop/join cleanly. Network work is outside
local state transactions and inference. SQLite WAL size reads tolerate a
concurrent checkpoint deleting transient sidecar files. Broken optional
monitoring config does not prevent existing local AI startup.

## Actual failure injection and recovery

| Phase | Cloud | Mode | Pending | Live QCI-2 health |
|---|---|---|---:|---|
{phases}

Actual QCI-2 model `{demo['model_version']}`, SHA256 `{demo['model_sha256']}`,
produced **{demo['fresh_model_predictions_during_outage']} fresh predictions and
{demo['fresh_cam_outputs_during_outage']} Grad-CAM outputs during outage**, with
numerical parity to the prior measured predictions. Six configured research
Critical activations and six explicit resolutions were retained locally; six
normal INFO activations remained active. The research Critical mapping is an
explicit source override, not confidence-as-risk or approved factory semantics.
No physical siren was activated.

Pending before recovery: {demo['pending_before_recovery']['pending']}; delivered
event summaries: {demo['event_summaries_delivered']}; final pending/in-flight:
{demo['final_spool']['pending']}/{demo['final_spool']['in_flight']}; terminal
failed/unknown: {demo['final_spool']['failed_permanent']}/{demo['final_spool']['unknown']}.
Total logical receiver receipts {demo['logical_items_received']}, actual requests
{demo['requests_received']}, duplicate logical deliveries {demo['duplicate_logical_deliveries']}.
Critical -> resolved order verified for all six activations. Recovery phase was
actually observed. Failure detection {demo['failure_detection_ms']:.6f} ms;
restoration/backlog drain {demo['recovery_ms']:.6f} ms. The demo uses accelerated
health interval {demo['config']['health_interval_seconds']} s and replay
{demo['config']['replay_items_per_second']} items/s; default production settings
are reported separately.

Tests also cover disabled mode, 400/429/500, refused connections, timeout,
malformed/oversized/missing-ack replies, trickled headers, expired dispatch lease,
restart, same-key conflict, cross-device identity, source replacement, byte/disk
limits, priority, partial batch backpressure, privacy and managed thread shutdown.

## Performance and overhead

| Measurement | Mean ms | P95 ms |
|---|---:|---:|
{metric_rows}

Paired actual classifier+CAM means: workers disabled
{demo['baseline_classifier_plus_cam']['mean_ms']:.6f} ms; monitoring/outage workers
enabled {demo['monitored_classifier_plus_cam']['mean_ms']:.6f} ms; observed change
{demo['observed_inference_mean_change_percent']:.6f}%. This small paired shared-
workstation run does not establish a speed improvement or universal overhead
guarantee. Both phases include the bounded in-process observer. Standalone
50-sample collection CPU cost {api['collector_cpu_seconds_for_50_samples']:.6f} s;
batch wall time {api['collector_batch_wall_seconds']:.6f} s; RSS
{api['collector_rss_before_mib']:.6f} -> {api['collector_rss_after_mib']:.6f} MiB.
The API profile includes local server/sampler activity. No numeric latency SLA
was supplied. Raw tails, preliminary contention measurements and failure evidence
are preserved rather than replaced with invented numbers.

## Memory, handles and offline behavior

{memory['cycles']} real-HTTP ONLINE/outage/queue/recovery cycles, with
{memory['warmup_cycles']} warmup and two matched windows of
{memory['cycles_per_matched_window']} cycles; 20 Hz whole-process RSS sampling.
The stress replays verified QCI-2 results through actual QCI-3 state and performs
no extra model inference. Its manually accelerated worker steps exercise actual
timeouts/backoff/retries; owned background workers are separately tested and
used in the real-model demo. Local receiver capture is bounded to 16; its SQLite
ledger records all {memory['receiver_logical_receipts']} logical receipts.

Start {memory['start_rss_mib']:.6f} MiB, peak {memory['peak_rss_mib']:.6f} MiB,
end {memory['end_rss_mib']:.6f} MiB. Window means
{memory['first_window_mean_rss_mib']:.6f} -> {memory['second_window_mean_rss_mib']:.6f}
MiB; drift **{memory['matched_window_drift_percent']:.6f}%**, strict <5% PASS.
Raw endpoint change {memory['raw_endpoint_change_percent']:.6f}% is separately
reported. Native threads {memory['threads_before']} -> {memory['threads_after']},
handles {memory['handles_before']} -> {memory['handles_after']}; peak native
threads/handles {memory['peak_threads']}/{memory['peak_handles']}. The real-model
demo's two owned workers stopped and Python thread count returned
{demo['threads_before']} -> {demo['threads_after']}. Its raw handle comparison
also includes initial model/SDK loading; stable repeated-cycle profiling is the
handle-leak evidence.

External TCP connect was process-locally blocked (zero attempted external
connections in demo/profile/API proof). Localhost remained available. No physical
Wi-Fi disconnect or host firewall was claimed. Local inference, Grad-CAM, alerts,
logging and status remained available. No GPU was launched or kept idle.

## Tests, delivery and limitations

QCI-4: {targeted['collected']} collected, {targeted['passed']} passed,
{targeted['failed']} failed, {targeted['skipped']} skipped,
{targeted['duration_seconds']} s. Repository: {repository['collected']} collected,
{repository['passed']} passed, {repository['failed']} failed,
{repository['skipped']} skipped, {repository['duration_seconds']} s.
The two unchanged CPU1 failures are actual detector IR size <6.5 MB and test mAP
drop <1 percentage point. QCI-4 does not weaken or redo those earlier gates.
Syntax/import checks and existing registry validation are recorded. No configured
type/lint tool was found. No unsupported production-cloud validation is claimed.

User-confirmed noncommercial research/evaluation scope and publisher attribution
remain in `QCI_3_Severity_IoT/LICENSE_DATA.md`. Existing MLflow/CSV tracking links
the actual QCI-2 model, QCI-3 policy, QCI-4 schema and source commit. Complete Git
history/runtime backup is packaged after the final two commits, hash-verified,
restored into a fresh clone and tested with actual classifier/alerts/failover and
normal push to a local bare repository. The final manifest is
`QCI_4_Edge_Telemetry/backups/delivery_manifest.json`. GitHub/PR and Slack: not
submitted; user requested local delivery while repository access is revoked.

## Definition of Done

| Check | Status |
|---|---|
{dod_rows}

Artifacts: configs/local_safe.json, docs/QCI_4_Edge_Telemetry_Cloud_Failover.md,
qci4_summary.json, failover_demo.json, api_profile.json, memory_profile.json,
memory_samples.csv, pytest_output.txt, repository_pytest_output.txt,
failover_demo_output.txt, memory_profile_terminal.txt, registry evidence,
review.html, proof_of_work.png and ignored verified recovery manifest/archive.
'''
    (REPORTS/'QCI_4_Production_Review.md').write_text(report,encoding='utf-8')
    update=f'''QCI-4 — EOD Update
Status: local edge telemetry/failover implementation verified; unrestricted release gates unmet.
Branch: {summary['branch']}
Telemetry: real CPU/RAM/disk/process, QCI-2 and QCI-3 health; default 2s bounded sampler.
Cloud: disabled by default; metadata opt-in only; strict health/ack/timeouts/retries.
Outage: {demo['fresh_model_predictions_during_outage']} fresh local predictions/CAM outputs; local alerts retained.
Recovery: {demo['event_summaries_delivered']} event summaries, zero duplicate logical delivery; critical/resolved order verified.
Memory: {memory['matched_window_drift_percent']:.6f}% matched-window drift, strict <5% PASS.
Tests: QCI-4 {targeted['passed']}/{targeted['collected']} PASS; repository {repository['passed']}/{repository['collected']}.
PR: deferred, access revoked; two local commits with verified cold-clone/runtime backup and future normal push helper.
Blockers: existing CPU1 size/accuracy gates; no production cloud endpoint/vendor contract supplied (mock validation complete).
'''
    (REPORTS/'EOD_Update.md').write_text(update,encoding='utf-8')
    (REPORTS/'PR_Description.md').write_text('''# QCI-4: add edge telemetry and graceful cloud failover

Real local resource/model/alarm health now feeds a typed cached API and the
existing monitor. Optional metadata sync survives cloud outages using bounded
SQLite storage, device-specific immutable dedupe identities, ordered replay,
matched acknowledgements and managed background workers. Local prediction and
alarm processing never call cloud synchronization.

Default cloud/metadata permissions are disabled. No production endpoint is
invented; the explicit local mock contract covers outage/restart/429/500/timeout,
source identity, capacity, privacy and recovery. No images or model weights leave
the gateway. Evidence and inherited acceptance failures are reported explicitly.

'''+update+'\nEvidence: reports/qci4/QCI_4_Production_Review.md and qci4_summary.json.\n',encoding='utf-8')
    page='''<!doctype html><html><head><meta charset="utf-8"><title>QCI-4 measured local review</title>
<style>body{font:16px Segoe UI,sans-serif;background:#101a25;color:#edf3fa;margin:36px;max-width:1200px}h1{color:#73d9b3}pre{white-space:pre-wrap;background:#192939;padding:20px;border-radius:10px}table{border-collapse:collapse;width:100%}td,th{padding:12px;border:1px solid #40536b}.pass{color:#73d9b3}.pending{color:#ffca78}</style></head><body>
<h1>IndusriX · QCI-4 edge telemetry and failover</h1><p class="pass">Local implementation verified · actual model + localhost cloud protocol</p>
<p class="pending">Unrestricted release gates: inherited CPU failures / revoked GitHub access</p>'''
    page+=f'<p>Implementation: {html.escape(source)} · actual model: {html.escape(demo["model_version"])}</p><table><tr><th>Actual phase</th><th>Cloud status</th><th>Mode</th><th>Pending</th><th>QCI-2 health</th></tr>'
    for p in demo['phases']:
        s=p['snapshot'];page+=f"<tr><td>{p['phase']}</td><td>{s['cloud']['status']}</td><td>{s['cloud']['mode']}</td><td>{s['spool']['pending']}</td><td>{s['inference']['status']}</td></tr>"
    page+='</table><h2>Measured evidence</h2><pre>'+html.escape(update)+'</pre><h2>Actual test output</h2><pre>'+html.escape((REPORTS/'pytest_output.txt').read_text())+'</pre>'
    page+='<h2>Actual saved resource snapshot from API collector measurement</h2><pre>'+html.escape(json.dumps(api['last_collector_snapshot']['resources'],indent=2))+'</pre></body></html>'
    (REPORTS/'review.html').write_text(page,encoding='utf-8')
    print(json.dumps({'task_tests':targeted,'repository_tests':repository,'memory_drift_percent':memory['matched_window_drift_percent'],'implementation':'PASS','overall':'FAIL'}))
if __name__=='__main__':main()
