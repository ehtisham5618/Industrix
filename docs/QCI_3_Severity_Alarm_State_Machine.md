# QCI-3 local severity and siren bridge

QCI-3 consumes the existing Pydantic `PredictionResult` from QCI-2. It never
loads a classifier, changes its prediction, or converts a Grad-CAM maximum into
an anomaly score. Actual classes are `normal` (0) and `defect` (1); confidence
is classification certainty, not industrial risk.

```
Actual QCI-2 inference + Grad-CAM (existing caller)
  -> Event validation: source_id, activation event_id, sequence, UTC observation
  -> existing SED-2 SeverityEngine through explicit QCI class configuration
  -> monotonic state transition + local SQLite audit + durable outbox commit
  -> typed status/API -> existing Streamlit quality status panel
  -> managed outbox worker -> bounded HTTP -> matched receiver acknowledgement
```

## Research policy and activation identity

`QCI_3_Severity_IoT/configs/local_research.json` explicitly maps normal to INFO
and defect to WARNING. Default rules have no timed escalation and no automatic
Critical mapping for a generic cosmetic defect. The webhook is disabled.
The local demo explicitly overrides `demo.critical` defects to CRITICAL to
exercise the bridge. Tests also exercise explicit persistence thresholds. These
are research/test policies; factory production severity rule approval is not
claimed. The user confirmed noncommercial research/evaluation; see
`QCI_3_Severity_IoT/LICENSE_DATA.md` for publisher terms and attribution.

Caller identity is `(source_id,event_id)`, not the image basename. A `sample_id`
must stay consistent within one activation; separate physical items with the
same filename require separate activation IDs/sources. A duplicate sequence must
have byte-equivalent typed event content. Lower sequence numbers, older
observations, conflicting sequence reuse, failed predictions, score argmax
mismatches, unknown model versions/classes and malformed metadata are rejected.
New observations do not downgrade an active severity. This layer trusts an
authorized upstream caller's observation timestamps and source identities;
it does not independently verify physical persistence or camera identity.

| From | Allowed next states |
|---|---|
| INACTIVE | INFO, WARNING, CRITICAL |
| INFO | WARNING, CRITICAL, RESOLVED |
| WARNING | CRITICAL, RESOLVED |
| CRITICAL | RESOLVED |
| RESOLVED | none; recurrence needs a new event_id |

Unchanged active severity updates metadata and emits no new action. Resolution
is explicit and idempotent. It cancels pending unsent activations; an already
in-flight POST may still reach its receiver. Resolution does not assert that a
physical siren stopped and sends no invented PLC/reset command.

| Tier | Actions on entry/escalation |
|---|---|
| INFO | SQLite structured audit, informational dashboard state |
| WARNING | SQLite structured audit, dashboard warning |
| CRITICAL | SQLite audit, critical dashboard, one logical siren activation |

## Persistence, concurrency and retention

QCI-3 uses prefixed `qci3_*` tables alongside the existing local SQLite design;
existing incident tables and bounding-box requirements are preserved. WAL and
SQLite `BEGIN IMMEDIATE` atomically commit state, audit and a unique outbox item.
There are no in-memory histories/image tensors or unbounded queues. Default
limits: 512 active records, 10,000 total records, 256 pending/in-flight deliveries,
50,000 audit entries, resolved TTL 86,400 seconds. Listing is capped at 100 rows.
Configured TTL is at least one second. Capacity errors preserve live Critical
events; a full outbox records FAILED delivery and queue backpressure while
preserving the Critical state. A full event store returns HTTP 503.

Resolved records expire only after pending/in-flight jobs finish. Their completed
outbox records are removed too. A persistent UTC observation watermark rejects
replays at or before the newest expired observation. Late observations from
other sources can therefore be rejected after retention cleanup: callers need
synchronized clocks and ordered observations. Idempotency is guaranteed within
retained activation history; after retention, callers must never recycle old
activation IDs with a newly invented timestamp. Audit retention is bounded and
is not an indefinite compliance archive. Retention protects active Critical rows
from eviction; they require explicit resolution.

Policy/config SHA256 is stored in the database. Changing it fails fast instead
of silently reinterpreting live state; choose a new database or a reviewed
migration. One process-managed worker services only Critical jobs, so lower
tiers cannot starve the siren queue. SQLite claims/leases also protect against
concurrent worker instances. Shutdown stops and joins the owned worker.

## Webhook contract and outcomes

URL comes from configuration or `QCI3_SIREN_URL`; enabling remains explicit in
configuration. Only numeric loopback/private LAN IPs are accepted, with HTTP(S),
no embedded credentials/query strings, no redirects and no DNS/cloud requirement.
Optional Bearer authentication is read at dispatch from the environment variable
named by `token_environment` (default `QCI3_SIREN_TOKEN`). Tokens never enter
payloads, database logs or status. The API is intended for a trusted local
gateway network; put existing deployment authentication in front of event/resolve
routes when exposing them beyond that boundary.

POST JSON includes `delivery_id`, `source_id`, `event_id`, actual `sample_id`,
`severity="critical"`, `action="ACTIVATE_SIREN"`, actual class/confidence,
observation time, model version and policy version. No heatmap binary is sent.
`Idempotency-Key` is the same UUID for all attempts. The receiver must durably
deduplicate this key before actuation for safe retries/exactly-once actuation.
This bridge alone cannot guarantee hardware exactly-once delivery across a
network failure.

Default timeout is one second, at most three attempts, exponential backoff
0.1/0.2 seconds. Retrying requires `receiver_idempotent=true`; otherwise use
one attempt. An absolute deadline covers HTTP request/response and bounded
8 KiB body reads. HTTPS connection establishment may involve both TCP and TLS
timeout intervals (conservative connection bound: twice the configured timeout);
it is checked against the deadline before dispatch. OS scheduling and local
database work are reported separately from socket deadlines. No retry is
unbounded and no network work holds the local state transaction. Expired dispatch
leases are retried only under the declared receiver idempotency contract and
remaining attempt budget; otherwise their outcome becomes DELIVERY_UNKNOWN.

Required successful response:

```json
{"delivery_id":"same-request-UUID","acknowledged":true}
```

| Outcome | Recorded result |
|---|---|
| 2xx plus matching acknowledgement | ACKNOWLEDGED (receiver acknowledgement, not measured hardware sound) |
| 2xx without matching acknowledgement | DELIVERY_UNKNOWN |
| 4xx | FAILED, no retry |
| 5xx | bounded retry; FAILED if exhausted |
| timeout/unreachable/dropout | bounded retry when safe; DELIVERY_UNKNOWN if exhausted |
| redirect/oversized response | DELIVERY_UNKNOWN; no redirect followed |
| disabled webhook | DISABLED; no HTTP |
| resolved before dispatch | FAILED/cancelled; no unsent activation |

Critical state is preserved for every delivery failure. Delivery attempts, last
HTTP status, error category and worker status are available without credentials.

## Local use and verification

Run from repository root with the existing CPU environment:

```powershell
$python = 'ESE_CPU1_Quantization/runtime/venv/Scripts/python.exe'
& $python -X utf8 -m pytest QCI_3_Severity_IoT/tests -q
& $python -X utf8 -m QCI_3_Severity_IoT.verify
$env:QCI3_CONFIG = 'QCI_3_Severity_IoT/configs/local_research.json'
& $python -m uvicorn Backend.main:api_app --host 127.0.0.1 --port 8000
```

Endpoints: GET `/qci3/status`, POST `/qci3/events` (`Event` JSON), POST
`/qci3/resolve` (`source_id,event_id,observed_at`). POST bodies are limited to
64 KiB; response listings and prediction metadata are bounded. Unknown fields
and duplicate JSON configuration keys are rejected. The existing Streamlit
monitor tab reads status and displays tier, state, last transition and delivery.

Verification runs genuine fresh QCI-2 checkpoint/CAM predictions in a separate
caller process, then sends those outputs through QCI-3 to a software-only
localhost mock receiver. External TCP is blocked in the verification process;
this is not a claimed physical network disconnect or host firewall. No real
siren is contacted. Tests exercise 400/500/timeout/dropout, resolution,
restart leases, duplicate/concurrent calls, capacity and TTL.

The RSS stress uses continuous 20 Hz sampling, 500 warmup events and two equal
2,500-event windows. Report start/peak/end RSS and raw endpoint change as well
as strict <5% drift between matched window means. Decision/transition/local
SQL-action timings are measured separately; local action timing excludes final
transaction commit, which is included in full core latency. HTTP and worker
dispatch timings are separate. No numeric product latency SLA was supplied.

Measured evidence is in `reports/qci3/`. GitHub access is revoked; local commits
and verified recovery artifacts preserve the work until normal branch sync is
available. Existing CPU acceptance thresholds remain unchanged and any unmet
quantitative gate is reported explicitly.
