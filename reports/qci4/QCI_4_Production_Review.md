# QCI-4 production review evidence

The optional local edge telemetry/failover implementation is verified. Overall
unrestricted release remains **FAIL** because whole-repository tests retain two
prior CPU1 acceptance failures and repository access prevents PR submission.
No existing failure or threshold was suppressed. This task does not retrain or
redo QCI-1/QCI-2/QCI-3; QCI-2 received only a bounded local observer hook.

Branch `feature/sprint2-qci4-edge-telemetry-failover` builds on `feature/sprint2-qci3-severity-iot-alerts` at
`bf50aabefba2812036b2de03cd6c718af995d1d0`. Implementation commit `a6256908205ea58dcd616503e81b8e01d1decc10`. Exactly two task
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
made 60 GET requests, with 10
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
| online | ONLINE | CONNECTED | 0 | HEALTHY |
| offline | OFFLINE | LOCAL_ONLY | 1 | HEALTHY |
| queued_during_outage | OFFLINE | LOCAL_ONLY | 19 | HEALTHY |
| recovering | RECOVERING | RECOVERING | 18 | HEALTHY |
| restored | ONLINE | CONNECTED | 0 | HEALTHY |

Actual QCI-2 model `qci2-kolektor-resnet18-v1`, SHA256 `00f626cf837139c3476dd4f2c77b4b0a8faa7e4b368af13936b33ddca838b795`,
produced **12 fresh predictions and
12 Grad-CAM outputs during outage**, with
numerical parity to the prior measured predictions. Six configured research
Critical activations and six explicit resolutions were retained locally; six
normal INFO activations remained active. The research Critical mapping is an
explicit source override, not confidence-as-risk or approved factory semantics.
No physical siren was activated.

Pending before recovery: 19; delivered
event summaries: 18; final pending/in-flight:
0/0; terminal
failed/unknown: 0/0.
Total logical receiver receipts 19, actual requests
20, duplicate logical deliveries 0.
Critical -> resolved order verified for all six activations. Recovery phase was
actually observed. Failure detection 132.898100 ms;
restoration/backlog drain 2856.931100 ms. The demo uses accelerated
health interval 0.1 s and replay
100.0 items/s; default production settings
are reported separately.

Tests also cover disabled mode, 400/429/500, refused connections, timeout,
malformed/oversized/missing-ack replies, trickled headers, expired dispatch lease,
restart, same-key conflict, cross-device identity, source replacement, byte/disk
limits, priority, partial batch backpressure, privacy and managed thread shutdown.

## Performance and overhead

| Measurement | Mean ms | P95 ms |
|---|---:|---:|
| Standalone collector | 21.522246 | 26.801100 |
| Actual localhost GET /edge/status | 8.714578 | 10.645000 |
| Spool batch incl. durable commit | 34.660213 | 42.501600 |
| Cloud POST transport | 25.790039 | 47.000000 |
| Local alarm core during outage | 44.742325 | 192.631700 |

Paired actual classifier+CAM means: workers disabled
696.027158 ms; monitoring/outage workers
enabled 1670.761633 ms; observed change
140.042592%. This small paired shared-
workstation run does not establish a speed improvement or universal overhead
guarantee. Both phases include the bounded in-process observer. Standalone
50-sample collection CPU cost 1.046875 s;
batch wall time 1.628072 s; RSS
59.105469 -> 58.898438 MiB.
The API profile includes local server/sampler activity. No numeric latency SLA
was supplied. Raw tails, preliminary contention measurements and failure evidence
are preserved rather than replaced with invented numbers.

## Memory, handles and offline behavior

1300 real-HTTP ONLINE/outage/queue/recovery cycles, with
300 warmup and two matched windows of
500 cycles; 20 Hz whole-process RSS sampling.
The stress replays verified QCI-2 results through actual QCI-3 state and performs
no extra model inference. Its manually accelerated worker steps exercise actual
timeouts/backoff/retries; owned background workers are separately tested and
used in the real-model demo. Local receiver capture is bounded to 16; its SQLite
ledger records all 2600 logical receipts.

Start 49.515625 MiB, peak 58.078125 MiB,
end 57.363281 MiB. Window means
56.248168 -> 56.977850
MiB; drift **1.297255%**, strict <5% PASS.
Raw endpoint change 15.848848% is separately
reported. Native threads 6 -> 3,
handles 224 -> 223; peak native
threads/handles 10/237. The real-model
demo's two owned workers stopped and Python thread count returned
1 -> 1. Its raw handle comparison
also includes initial model/SDK loading; stable repeated-cycle profiling is the
handle-leak evidence.

External TCP connect was process-locally blocked (zero attempted external
connections in demo/profile/API proof). Localhost remained available. No physical
Wi-Fi disconnect or host firewall was claimed. Local inference, Grad-CAM, alerts,
logging and status remained available. No GPU was launched or kept idle.

## Tests, delivery and limitations

QCI-4: 49 collected, 49 passed,
0 failed, 0 skipped,
54.68 s. Repository: 397 collected,
395 passed, 2 failed,
0 skipped, 127.58 s.
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
| Required feature branch used | PASS |
| QCI-2/QCI-3 local pipeline remains independent of cloud | PASS |
| Pydantic v2 telemetry contracts implemented/reused | PASS |
| CPU telemetry implemented | PASS |
| RAM telemetry implemented | PASS |
| Disk/spool telemetry implemented | PASS |
| Inference health telemetry implemented | PASS |
| Alert health telemetry implemented | PASS |
| Cloud health detection implemented (local mock) | PASS |
| Cloud-disabled state implemented | PASS |
| Graceful offline/local-only mode implemented | PASS |
| Cloud failure does not block inference | PASS |
| Local durable spool implemented/reused | PASS |
| Spool is bounded | PASS |
| Retries are bounded | PASS |
| Timeouts implemented | PASS |
| Exponential backoff implemented | PASS |
| Idempotent replay/deduplication implemented | PASS |
| Restart-safe pending sync implemented | PASS |
| Cloud recovery implemented | PASS |
| Pending items replay after recovery | PASS |
| Network dropout test passes | PASS |
| 429/500/timeout scenarios handled | PASS |
| Malformed cloud response handled | PASS |
| Clean shutdown implemented | PASS |
| Memory profile measured | PASS |
| Offline core execution verified | PASS |
| Documentation completed | PASS |
| Proof-of-work generated | PASS |
| Memory drift <5% | PASS |
| Automated QCI-4 tests 100% passing | PASS |
| Automated whole-repository tests 100% passing | FAIL |
| PR opened | FAIL / deferred: user reports revoked repository access; local delivery requested |
| QCI-4 OVERALL | FAIL for unrestricted release: inherited CPU gates and deferred PR; local implementation verified |

Artifacts: configs/local_safe.json, docs/QCI_4_Edge_Telemetry_Cloud_Failover.md,
qci4_summary.json, failover_demo.json, api_profile.json, memory_profile.json,
memory_samples.csv, pytest_output.txt, repository_pytest_output.txt,
failover_demo_output.txt, memory_profile_terminal.txt, registry evidence,
review.html, proof_of_work.png and ignored verified recovery manifest/archive.
