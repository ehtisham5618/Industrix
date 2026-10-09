# QCI-4 edge telemetry and graceful cloud failover

QCI-4 monitors the existing local QCI pipeline. It never substitutes cloud
inference for the QCI-2 model and never owns QCI-3 severity/siren state.
Cloud synchronization is optional and disabled by default. No production cloud
endpoint or vendor protocol was supplied; the implemented protocol is verified
against an explicitly configured software localhost receiver.

```
QCI-2 actual local predict -> bounded in-process inference tracker (weak reference)
QCI-1 saved manifest ----> background health/resource collector
QCI-3 local SQLite ------> read-only alarm health + bounded audit summaries
                                  |
                          cached typed local status -> existing API/Streamlit
                                  |
                    optional allowlisted metadata -> durable SQLite spool
                                  |
                       managed sync worker + service-specific health check
                                  |
                  DISABLED / UNKNOWN / ONLINE / DEGRADED / OFFLINE
                                  |
                      RECOVERING -> acknowledged ordered replay -> ONLINE
```

## Real telemetry and process boundaries

The collector reuses SED-3 `ResourceMonitor.sample()` with GPU and thermal
inspection disabled. It does not start that older monitor's unbounded-history
thread; its exception history is bounded to eight entries. Additional psutil
calls supply disk, RAM used, process uptime and handles. CPU calls are
nonblocking. The first CPU sample in a sampling thread is unavailable (`null`)
because psutil has not measured an interval yet. System CPU percent is primary;
raw process CPU percent can exceed 100 across multiple cores. Memory uses MiB,
despite the compatible API field suffix `_mb`.

| Metric | Actual source | Unit / interval |
|---|---|---|
| System/process CPU | existing SED-3 sampler + psutil | %, nominal 2 s |
| System RAM used / utilization | psutil.virtual_memory | MiB / %, 2 s |
| Process RSS, threads, handles, uptime | psutil.Process | MiB/count/seconds, 2 s |
| Disk usage / free space | local database filesystem | %/bytes, 2 s |
| QCI-1 dataset health | saved validation manifest | cached by file mtime; not a rescan |
| Model loaded/version | weak reference to actual QCI-2 instance | sampled; unknown if uninstrumented |
| Classifier/combined latency and call count | actual QCI-2 returned results | each prediction; recent 128 calls |
| INFO/WARNING/CRITICAL and webhook outcomes | existing QCI-3 SQLite tables | read-only, 2 s |
| Queue depth/bytes/age, receipts, failures | owned prefixed SQLite spool tables | actual database state |
| Service health / last sync | actual configured HTTP response and matched ack | nominal 10 s probe / each delivery |

QCI-2 has a small backwards-compatible optional observer hook. It only updates
bounded local counters/latency deques and never calls HTTP or SQLite. Observation
failure is logged by error category and cannot alter the prediction. The tracker
does not retain models, tensors, image paths or heatmaps. Its scope is the most
recent bound QCI-2 classifier in this process; another process or the legacy
12-class YOLO engine is not falsely reported as this classifier. No inference
is run just to collect health. Counts reset with the process; saved QCI-2 reports
are not fabricated as current live inference telemetry.

QCI-3 counts come from its actual retained event/outbox/audit tables. They are
retained-state counts, not lifetime totals. An uninitialized database, missing
tables, read failure or unavailable model yields UNKNOWN/null/error categories,
not invented zeros or success. QCI-1 MANIFEST_VALIDATED means the saved report
says SUCCESS; it does not independently revalidate every image on each sample.

## Health and failover states

Edge: HEALTHY, DEGRADED, OFFLINE_LOCAL_ONLY, ERROR. Missing/stale local evidence
is DEGRADED; actual inference/alarm errors are ERROR. If local health is otherwise
healthy and cloud operations fail, the edge reports OFFLINE_LOCAL_ONLY. Cloud
failure does not disable local inference, Grad-CAM, SQLite alarms or the UI.

Cloud: DISABLED, UNKNOWN, ONLINE, DEGRADED, OFFLINE, RECOVERING. Mode is
LOCAL_ONLY, RECOVERING or CONNECTED. Disabled integration makes no HTTP calls
and starts no sync worker. Enabled startup is UNKNOWN until a real service
check. The configured health endpoint must return HTTP 200 plus
`{"status":"ok","service":"qci4-sync-v1"}` (configured expected service).
DNS, Wi-Fi or a generic public-IP ping never proves this service ONLINE.

The first failed operation activates LOCAL_ONLY immediately; two consecutive
failed health checks (default) yield OFFLINE. A healthy health endpoint with
upload failures remains DEGRADED. Health and sync outcomes are separate fields.
A successful health check does not erase an unresolved upload failure.
Successful health after outage enters RECOVERING; acknowledged backlog drain
reaches ONLINE. Permanent/unknown delivery failures remain explicitly degraded.
Restart preserves pending items and last acknowledged sync time, but cloud
connectivity restarts UNKNOWN until checked again.

## Durable spool, priority, ordering and privacy

QCI-4 adds `qci4_*` tables to the repository's existing local SQLite design.
When event sync is enabled, a QCI-4-owned one-row source identity marker is
initialized in the alarm database. QCI-3's own tables remain read-only to this
collector. Subsequent reads verify this marker; a different source or regressed
audit counter cannot silently reuse the saved cursor. Identical database
relocation/restore keeps the marker and cursor identity.
Unrelated incident/QCI-3 tables and schema versions are preserved. Transactions
atomically store payload, digest, dedupe identity and QCI-3 collection cursor.
Audit summaries are written in batches of at most 32 rows to reduce filesystem
commits. The cursor only advances for accepted/skipped nontransition rows and
never moves backwards. On capacity overflow an accepted prefix commits and the
remaining QCI-3 audit stays available for the next collection attempt.

Only explicitly permitted typed metadata can leave the device:

* telemetry: observation time, CPU/RAM/RSS/disk gauges, inference count/latency,
  active alert count, edge state;
* event summary: salted activation hash, audit sequence, state/severity,
  observation time, model/policy version.

Raw images, heatmaps, tensors, checkpoints, private source/event names, paths,
hostnames, raw exception messages and credentials are excluded by Pydantic
allowlists. Event/source identity is pseudonymized with a persistent device UUID;
hashing is not an anonymity claim. Enabling the service alone does not permit
uploads: `allow_telemetry_sync` and/or `allow_event_sync` must be explicitly true.
Default settings permit neither. The existing console's core-cloud-dependency
indicator describes local AI; the new panel separately exposes optional outbound
permissions and cloud-sync state.

Default spool limits: 1,000 rows, 1,048,576 payload bytes, 8 KiB per item, 32
routine items, 1-hour routine TTL, 10,000 dedupe receipts, 7-day receipt TTL,
1,000 structured audit records and a 100 MB disk-free reserve. Database/WAL/SHM
bytes are measured separately and include other tables when storage is shared.
Owned payload/receipt/log cardinalities are bounded; filesystem/database overhead
is not falsely equated to payload bytes. WAL uses existing SQLite lifecycle
checkpointing; connections close after each bounded transaction.

Routine samples are downsampled to one per 60 seconds (default), capped and
expired. Critical > Warning > Info event summaries precede routine telemetry.
Unattempted pending routine samples can be displaced for events, with counters.
Attempted items remain immutable. Critical/event data is never silently expired
or evicted. If the bounded store/disk reserve is full, backpressure is logged and
the source cursor is retained; local QCI-3 state is preserved. A sufficiently
long outage can exceed QCI-3's own finite audit retention. A detected source gap
is exposed as `qci3_audit_retention_gap`, not falsely claimed complete sync.

Transitions for one activation cannot overtake an earlier undelivered transition:
resolved cannot arrive before critical. A permanent/unknown predecessor blocks
its activation's later transitions and needs operator review; other activations
can still progress. No automatic blind replay of exhausted/unknown jobs exists.

Device-specific receiver keys are `device UUID : SHA256(logical key)`; a second
device's audit row 1 cannot collide with the first. Item IDs are deterministic
UUID5 values. Duplicate immutable payloads reuse the identity; conflicting key
reuse is rejected. Matched acknowledgements create durable receipts. After
bounded receipt eviction/expiry, a persistent observation watermark rejects old
replays. Callers must not recycle identities with newly invented timestamps;
this is bounded-history dedupe, not an infinite archive. Restore preserves device
identity; independent new devices need independent stores.

## Cloud protocol, security, retries and lifecycle

The current bounded connector accepts numeric IP base URLs. This avoids an
unbounded DNS resolver inside the timeout contract; named-host cloud endpoints
need a bounded resolver adapter/vendor integration before use. HTTPS verifies
certificates by default, including IP SAN matching. Plain HTTP is allowed only
for loopback tests. No credential-in-URL, query secrets, redirects or TLS bypass
are accepted. Health/upload paths are explicitly configured, not presumed to
exist on an unspecified production service.

Optional Bearer authentication is read at dispatch from the environment variable
named in config (default `INDUSRIX_CLOUD_TOKEN`). Values are never persisted or
returned in status. The wire protocol expects bounded UTF-8 JSON with a valid
Content-Length; chunked/encoded/oversized/malformed responses fail closed. Both
headers and body are capped at 8 KiB and read under one absolute response deadline,
so trickled headers cannot reset a read timeout forever. Default HTTP timeout is
1 s; TCP/TLS connection establishment has a conservative bound of twice that
configured interval. OS scheduling/local database overhead are measured separately
and no hard real-time guarantee is invented.

Upload body: `schema_version`, `item_id`, `dedupe_key`, `payload_sha256`, typed
`payload`. Idempotency-Key matches `dedupe_key`. A successful acknowledgement
must contain matching item/key/digest and literal `accepted: true` with 2xx.
2xx alone is not delivery. The receiver must durably deduplicate before accepting
data; client-side retries alone cannot guarantee exactly-once across a network.

Per-item attempts are bounded (default 3). Exponential delays start at 1 s,
cap at 60 s, with up to 10% independent device jitter. 429 Retry-After (integer
seconds or date) is sanitized/capped and respected. 500/transport/malformed-ack
failures retry within budget; other 4xx and redirects are permanent. Exhausted
ambiguous outcomes are DELIVERY_UNKNOWN. PENDING, IN_FLIGHT, FAILED_RETRYABLE,
DELIVERED, FAILED_PERMANENT and DELIVERY_UNKNOWN remain explicit. Crashed
in-flight leases retry only under the declared idempotent receiver contract and
remaining budget. Uploads are limited to 5 items/s by default; priorities preserve
activation order. Periodic bounded health probes continue at a capped interval
to detect restoration, rather than endlessly retrying an individual item.

One managed sampler and (only when enabled) one sync worker are owned by the
API/service. Network work never holds a spool/alert transaction. Shutdown signals
and joins workers, closes connections and leaves undelivered items durable.
An invalid optional monitoring configuration reports monitoring unavailable and
does not prevent existing local AI startup. No cloud-config endpoint is exposed;
configuration belongs to the trusted gateway operator. A changed enabled spool
policy needs a new store/reviewed migration; disabling preserves pending data,
and re-enabling the identical policy is supported.

## Running and evidence

```powershell
$python = 'ESE_CPU1_Quantization/runtime/venv/Scripts/python.exe'
$env:QCI4_CONFIG = 'QCI_4_Edge_Telemetry/configs/local_safe.json'
& $python -m uvicorn Backend.main:api_app --host 127.0.0.1 --port 8000
& $python -X utf8 -m pytest QCI_4_Edge_Telemetry/tests -q
& $python -X utf8 -m QCI_4_Edge_Telemetry.verify demo
& $python -X utf8 -m QCI_4_Edge_Telemetry.verify profile
```

GET `/edge/status` returns typed health, cached hardware/pipeline metrics and
current cloud/spool state without HTTP. GET `/edge/history?limit=20` returns at
most 100 entries from the bounded 300-snapshot ring. The existing Streamlit monitor
adds a small edge/cloud panel and distinct disabled/offline/recovering banners.
`INDUSRIX_CLOUD_ENABLED` (`true`/`false`) and `INDUSRIX_CLOUD_URL` optionally
override config; enabling needs explicit protocol paths, permissions and receiver
idempotency in the config. Tokens stay in the environment.

The real-model demo invokes actual QCI-2 prediction/Grad-CAM during a localhost
service outage, creates actual QCI-3 states, then observes recovery and ordered
acknowledgement. External TCP connect is blocked process-locally; this is not
a claimed physical internet disconnect or OS firewall. No external cloud service
or physical siren is contacted, no GPU is required and no model is retrained.

Memory stress uses 1,300 real-HTTP failover cycles with replay of verified QCI-2
results through QCI-3 (not 1,300 fresh inferences), 300 warmup cycles and two equal
500-cycle windows. RSS is sampled at 20 Hz; start/peak/end and endpoint change are
reported alongside strict <5% matched-window drift. The local mock capture ring
is capped at 16 for profiling; its durable receipt ledger records every logical
item. Owned worker lifecycle is tested separately and used in the real-model demo.
Latency timings use bounded deques, retain tails and do not invent a numeric SLA.
CPU overhead and paired inference timings are measured on a shared workstation,
not presented as exclusive-machine or universal performance guarantees.

See `reports/qci4/` for measured evidence, full test output, failure injection,
production-review report, summary JSON and proof. Existing unrelated CPU detector
acceptance failures remain visible in repository-wide testing; QCI-4 does not
retrain/alter those earlier tasks. GitHub access is revoked, so two local commits,
complete-history bundle, hash-verified runtime archive, cold-clone demonstration
and normal future-push proof provide the requested local delivery.
