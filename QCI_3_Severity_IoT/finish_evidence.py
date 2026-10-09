"""Render measured local review evidence; never substitute synthetic metrics."""
from pathlib import Path
import hashlib
import html
import json
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1];REPORTS=ROOT/'reports/qci3'

def tests(path):
    text=path.read_text(encoding='utf-8')
    lines=[line for line in text.splitlines() if re.search(r'\d+ passed',line)]
    line=lines[-1]
    result={key:int(re.search(r'(\d+) '+key,line).group(1)) if re.search(r'(\d+) '+key,line) else 0 for key in ('passed','failed','skipped','errors')}
    result['collected']=sum(result.values());result['duration_seconds']=float(re.search(r'in ([\d.]+)s',line).group(1))
    result['summary']=line;return result

def main():
    demo=json.loads((REPORTS/'loopback_demo.json').read_text());memory=json.loads((REPORTS/'memory_profile.json').read_text())
    cpu=json.loads((REPORTS/'cpu_acceptance_followup.json').read_text());targeted=tests(REPORTS/'pytest_output.txt');repository=tests(REPORTS/'repository_pytest_output.txt')
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    checks={key:'PASS' for key in ['Required feature branch used','QCI-2 event contract consumed','Pydantic v2 contracts implemented/reused',
        'INFO tier implemented','WARNING tier implemented','CRITICAL tier implemented','Severity rules externally configurable',
        'No invented class mappings','State machine implemented','Valid transitions tested','Invalid transitions handled',
        'Event idempotency implemented','Critical siren triggers once per activation','Webhook client implemented','Webhook timeout implemented',
        'Bounded retry policy implemented','Webhook failure does not crash local pipeline','Webhook-disabled mode works',
        'Offline/local mode works','Local mock webhook tests pass','Concurrent events isolated','Resolved events cleaned/evicted',
        'Bounded in-memory state implemented','Structured logging implemented','Structured JSON/Pydantic output implemented',
        'Memory profile measured','Documentation completed','Proof-of-work generated','Dataset permission for current research use']}
    checks['Memory drift <5%']='PASS' if memory['strict_less_than_5_percent_pass'] else 'FAIL'
    checks['Automated QCI-3 tests 100% passing']='PASS' if targeted['failed']==targeted['errors']==0 else 'FAIL'
    checks['Automated repository tests 100% passing']='PASS' if repository['failed']==repository['errors']==0 else 'FAIL'
    checks['PR opened']='FAIL (user reports GitHub access revoked; no push/PR attempted)'
    checks['QCI-3 OVERALL']='FAIL (repository CPU acceptance gates and PR submission remain unmet)'
    result={'task':'QCI-3','branch':'feature/sprint2-qci3-severity-iot-alerts','base_branch':'feature/sprint2-qci2-defect-classifier',
        'base_commit':'9daaa97e0f3c674095ec98a79f8d215a18bc3b2e','implementation_commit':commit,
        'qci2_model_version':'qci2-kolektor-resnet18-v1','dataset_permission':cpu['dataset_permission'],
        'targeted_tests':targeted,'repository_tests':repository,'memory':memory,'demo':demo,'cpu_followup':cpu,
        'feature_implementation':'PASS' if targeted['failed']==0 and memory['strict_less_than_5_percent_pass'] else 'FAIL',
        'overall':'FAIL','dod':checks,'github_pr':None,'production_iot_endpoint_provided':False,
        'factory_severity_rules_approved':False,'gpu_used':False,
        'browser_tool_bootstrap':'failed to write kernel assets: system cannot find path (os error 3); fresh headless Edge fallback',
        'recovery_evidence_location':'QCI_3_Severity_IoT/backups/delivery_manifest.json (generated after final two commits)'}
    (REPORTS/'qci3_summary.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    metrics='\n'.join(f'| {name} | {value} |' for name,value in checks.items())
    rows='\n'.join(f"| {name} | {demo[key]['mean_ms']:.6f} | {demo[key]['p95_ms']:.6f} |" for name,key in
        [('Severity decision','decision_latency'),('State transition','transition_latency'),('Local SQL actions, before final commit','local_action_latency'),
        ('Full local core incl. validation/commit','core_latency'),('HTTP transport only','http_latency'),('Worker dispatch incl. database','worker_dispatch_latency')])
    report=f'''# QCI-3 production review evidence

The local research alarm implementation is verified. **Overall acceptance remains
FAIL** because the existing CPU detector size/accuracy/throughput gates remain
unmet and repository access prevents PR submission. No tests or thresholds were
suppressed to turn this into a false pass. The dataset permission issue is
resolved for the user's confirmed noncommercial research/evaluation scope.

Branch: `{result['branch']}`; base: `{result['base_branch']}` at `{result['base_commit']}`.
Implementation commit: `{commit}`. Two task commits are saved locally; final
hashes and independently verified recovery are recorded in the ignored delivery
manifest after committing. Author: ehtisham5618 <ehtisham.malik5618@gmail.com>.

## Input, policy and actions

Actual model: `qci2-kolektor-resnet18-v1`, checkpoint SHA256
`00f626cf837139c3476dd4f2c77b4b0a8faa7e4b368af13936b33ddca838b795`.
Two fresh classifier/Grad-CAM results match their prior measured predictions.
The core consumes the unchanged QCI-2 Pydantic result inside a validated
source/activation/sequence/time envelope; it performs no inference itself.

Default policy: normal -> INFO; defect -> WARNING; no automatic Critical rule.
The software demo explicitly overrides defect on `demo.critical` -> CRITICAL.
These are documented research mappings, not approved factory hazard semantics.
No anomaly score, area, seven-class textile output or confidence-as-risk rule
is fabricated. Active states escalate monotonically; explicit resolution records
RESOLVED, cancels unsent delivery, and recurrence requires a new activation ID.
See [full transitions and limits](../../docs/QCI_3_Severity_Alarm_State_Machine.md).

INFO writes structured SQLite audit and informational status; WARNING adds
dashboard warning; CRITICAL adds critical status and one durable siren job.
The existing FastAPI and Streamlit monitor have minimal status integration.

## Webhook and actual localhost evidence

Disabled by default. URL is external configuration/`QCI3_SIREN_URL`, restricted
to numeric loopback/private LAN addresses. Optional Bearer secret comes from
`QCI3_SIREN_TOKEN` (or configured environment-variable name), never from Git.
Default deadline is 1 second, max 3 attempts, backoff .1/.2 seconds. HTTPS
TCP/TLS establishment has a conservative 2x connection-timeout bound. Retries
require receiver idempotency support. Network dispatch happens outside the
local state transaction; queue capacity failures preserve Critical status.

Actual local mock: {demo['mock_url']}. Received **{demo['requests_received']}**
POSTs for **{demo['acknowledged_activations']}** acknowledged logical activations,
including one 500 retry. **{demo['duplicate_inputs']}** duplicate inputs created
**{demo['duplicate_activations']}** duplicate activations. Every retry uses the
same Idempotency-Key. A matching JSON acknowledgement is required; 2xx alone
is DELIVERY_UNKNOWN. Tests also cover 400, exhausted 500, timeouts, missing
acknowledgement, redirects, dropped connections, unreachable endpoint, restart
leases, concurrent workers, cancellation and disabled mode.

Production IoT siren endpoint not provided. The receiver is software only;
acknowledgement is not evidence of physical siren sound. No GPIO/PLC was used.

## Latency

| Stage | Mean ms | P95 ms |
|---|---:|---:|
{rows}

Long-run core: mean {memory['core_latency']['mean_ms']:.6f} ms,
P95 {memory['core_latency']['p95_ms']:.6f} ms. These are measured local Windows
workstation results; no numeric product SLA was specified. HTTP, decision,
transition, local actions and full core are reported separately.

## Memory and offline verification

{memory['events']} actual event/resolution cycles; {memory['warmup_events']} warmup;
two matched windows of {memory['events_per_matched_window']} events, RSS sampled
continuously at {memory['sampling_hz']} Hz. Start {memory['start_rss_mib']:.4f} MiB,
peak {memory['peak_rss_mib']:.4f} MiB, end {memory['end_rss_mib']:.4f} MiB.
Window means {memory['first_window_mean_rss_mib']:.4f} ->
{memory['second_window_mean_rss_mib']:.4f} MiB; drift
**{memory['matched_window_drift_percent']:.6f}%**, strict <5%: PASS.
Raw endpoint change {memory['raw_endpoint_change_percent']:.6f}% is separately
reported and is not substituted for the specified matched-window drift.

External TCP was blocked in the verification process while loopback stayed
available: {demo['external_tcp_attempts']} external attempts. Fresh QCI-2
inference also ran with its existing external-network guard. No cloud service
is required; physical Wi-Fi/internet disconnect or OS firewall was not claimed.
The fixed-size state/outbox/audit limits and replay-retention contract are
documented. Source artifacts, profiles and terminal outputs are preserved.

## Tests and remaining CPU work

QCI-3: {targeted['collected']} collected, {targeted['passed']} passed,
{targeted['failed']} failed, {targeted['skipped']} skipped,
{targeted['duration_seconds']} seconds.
Whole repository: {repository['collected']} collected, {repository['passed']} passed,
{repository['failed']} failed, {repository['skipped']} skipped,
{repository['duration_seconds']} seconds. The two unchanged CPU1 failures are
actual IR size <6.5 MB and test mAP drop <1 percentage point.

Actual IR {cpu['current_ir_bytes']:,} bytes; dense INT8 constants alone
{cpu['dense_INT8_constant_bytes']:,} bytes. Lossless zlib trial still exceeds
the budget. Requested NNCF INT4 compression retained all convolution groups
at INT8 and produced 11,757,999 bytes; it was not mislabelled or deployed.
Full bias correction used the same 300 training-only calibration samples;
validation mAP50 {cpu['full_bias_candidate']['candidate_validation']['map50']:.9f}
vs existing {cpu['full_bias_candidate']['existing_validation']['map50']:.9f}, so
the worse candidate was rejected without test-set selection.

Recorded current test mAP drop: {cpu['current_recorded_test_map_drop_pp']:.9f} pp.
Fresh actual CPU inference: 30 warmups, 200 timed iterations, mean
{cpu['mean_ms']:.6f} ms, P95 {cpu['p95_ms']:.6f} ms, serial capacity
{cpu['serial_inference_capacity_fps']:.6f} FPS. This fails <20 ms and cannot
sustain the required 48 evaluated FPS on this serial model/workstation.
Preprocessing/NMS/decode are excluded, so full pipeline cannot be faster.
No smaller retrained model was silently substituted for required YOLOv8s and
no mixed-precision artifact was falsely called pure INT8. Resolving size needs
a changed model/precision contract; throughput needs measured suitable target
hardware or a separately evaluated smaller detector. Those alternatives are
not claimed complete. Modal is available but no GPU was launched, so no GPU
credits or idle connection were consumed by this task.

## Licensing, recovery and delivery

[Publisher terms](https://www.vicos.si/resources/kolektorsdd/) license KolektorSDD
under CC BY-NC-SA 4.0. The user confirmed noncommercial research/evaluation;
publisher commercial permission is not needed for this stated scope. Required
attribution/citation and data modifications are recorded in
[LICENSE_DATA.md](../../QCI_3_Severity_IoT/LICENSE_DATA.md).

MLflow/CSV tracking uses the existing registries with explicit rules, state-machine,
webhook and QCI-2 model versions. Complete Git bundle and per-member-hashed local
runtime archive are verified after the second commit; a cold clone must reproduce
actual classifier/CAM -> state -> localhost webhook and restored SQLite integrity.
The future push helper is tested against a local bare repository with no force
push. GitHub/PR: not submitted; access is revoked. No Slack/EOD message was sent.

## Definition of Done

| Check | Status |
|---|---|
{metrics}

Artifacts: `qci3_summary.json`, `loopback_demo.json`, `memory_profile.json`,
`memory_samples.csv`, `cpu_acceptance_followup.json`, `cpu_bias_candidate.json`,
`pytest_output.txt`, `repository_pytest_output.txt`, `verification_terminal.txt`,
`fresh_classifier_terminal.txt`, `proof_of_work.png`, `review.html`, registry
evidence and the ignored backup `delivery_manifest.json`.
'''
    (REPORTS/'QCI_3_Production_Review.md').write_text(report,encoding='utf-8')
    update=f'''QCI-3 — EOD Update
Status: Local research implementation verified; overall release gates unmet.
Branch: {result['branch']}
Severity: INFO/WARNING/CRITICAL, explicit research policy; monotonic state machine.
IoT: durable local outbox, bounded retries, {demo['requests_received']} actual mock requests,
{demo['acknowledged_activations']} acknowledged activations, no duplicate activations.
Offline: external TCP blocked; localhost enabled; no required cloud/GPU.
Memory: {memory['matched_window_drift_percent']:.6f}% matched-window drift, <5% PASS.
Tests: QCI-3 {targeted['passed']}/{targeted['collected']} PASS; repository {repository['passed']}/{repository['collected']}.
Dataset: noncommercial research/evaluation confirmed; publisher-license attribution recorded.
PR: not submitted, access revoked; exactly two local commits and verified future-sync backup.
Blockers: unchanged dense YOLOv8s CPU size/accuracy/throughput gates; factory rule approval only if later deployed.
'''
    (REPORTS/'EOD_Update.md').write_text(update,encoding='utf-8')
    (REPORTS/'PR_Description.md').write_text('''# QCI-3: add severity state machine and IoT siren webhook

QCI-2 normal/defect outputs now feed validated, monotonic local severity states
and a durable Critical outbox. Duplicate observations do not repeat actions;
network failures preserve local Critical state. The existing API/monitor show
state, last transition and acknowledged/failed/unknown delivery.

Default research policy is normal INFO / defect WARNING with webhook disabled.
Critical is explicitly configured in the local software demo. HTTP has bounded
timeouts/retries and requires a matched receiver acknowledgement and stable
Idempotency-Key. No production secrets or hardware actuation are included.

'''+update+'\nEvidence: reports/qci3/QCI_3_Production_Review.md and qci3_summary.json.\n',encoding='utf-8')
    page='''<!doctype html><html><head><meta charset="utf-8"><title>QCI-3 measured local review</title>
<style>body{font:16px Segoe UI,sans-serif;background:#101a25;color:#edf3fa;margin:36px;max-width:1200px}h1{color:#73d9b3}pre{white-space:pre-wrap;background:#192939;padding:20px;border-radius:10px}table{border-collapse:collapse;width:100%}td,th{padding:12px;border:1px solid #40536b}.pass{color:#73d9b3}.pending{color:#ffca78}</style></head><body>
<h1>IndusriX · QCI-3 measured local review</h1><p class="pass">Local research alarm implementation verified · software localhost receiver only</p>
<p class="pending">Overall acceptance: FAIL · existing CPU gates and revoked GitHub access</p>'''
    page+=f'<p>Source commit: {html.escape(commit)} · model: qci2-kolektor-resnet18-v1</p>'
    page+='<table><tr><th>Actual demo input</th><th>Tier</th><th>Delivery at local decision</th></tr>'
    for status in demo['first_states']:
        page+=f"<tr><td>{html.escape(status['source_id']+' / '+status['sample_id'])}</td><td>{status['severity'].upper()}</td><td>{status['delivery']}</td></tr>"
    page+='</table><h2>Measured proof</h2><pre>'+html.escape(update)+'</pre><h2>Actual test terminal output</h2><pre>'+html.escape((REPORTS/'pytest_output.txt').read_text())+'</pre>'
    page+='<h2>Actual receiver JSON</h2><pre>'+html.escape(json.dumps(demo['received_payloads'][:2],indent=2))+'</pre></body></html>'
    (REPORTS/'review.html').write_text(page,encoding='utf-8')
    print(json.dumps({'qci3_tests':targeted,'repository_tests':repository,'overall':'FAIL','feature_implementation':result['feature_implementation']}))

if __name__=='__main__':main()
