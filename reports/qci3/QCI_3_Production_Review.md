# QCI-3 production review evidence

The local research alarm implementation is verified. **Overall acceptance remains
FAIL** because the existing CPU detector size/accuracy/throughput gates remain
unmet and repository access prevents PR submission. No tests or thresholds were
suppressed to turn this into a false pass. The dataset permission issue is
resolved for the user's confirmed noncommercial research/evaluation scope.

Branch: `feature/sprint2-qci3-severity-iot-alerts`; base: `feature/sprint2-qci2-defect-classifier` at `9daaa97e0f3c674095ec98a79f8d215a18bc3b2e`.
Implementation commit: `3be0bc329b61862c7ceb6e6f3a9c3ce96ce5fa5e`. Two task commits are saved locally; final
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

Actual local mock: http://127.0.0.1:56842/siren. Received **101**
POSTs for **100** acknowledged logical activations,
including one 500 retry. **1020** duplicate inputs created
**0** duplicate activations. Every retry uses the
same Idempotency-Key. A matching JSON acknowledgement is required; 2xx alone
is DELIVERY_UNKNOWN. Tests also cover 400, exhausted 500, timeouts, missing
acknowledgement, redirects, dropped connections, unreachable endpoint, restart
leases, concurrent workers, cancellation and disabled mode.

Production IoT siren endpoint not provided. The receiver is software only;
acknowledgement is not evidence of physical siren sound. No GPIO/PLC was used.

## Latency

| Stage | Mean ms | P95 ms |
|---|---:|---:|
| Severity decision | 0.033127 | 0.045500 |
| State transition | 0.011816 | 0.014400 |
| Local SQL actions, before final commit | 0.770763 | 0.907300 |
| Full local core incl. validation/commit | 15.114102 | 18.473200 |
| HTTP transport only | 14.888901 | 39.031200 |
| Worker dispatch incl. database | 17.575146 | 49.830300 |

Long-run core: mean 23.786589 ms,
P95 31.902600 ms. These are measured local Windows
workstation results; no numeric product SLA was specified. HTTP, decision,
transition, local actions and full core are reported separately.

## Memory and offline verification

5500 actual event/resolution cycles; 500 warmup;
two matched windows of 2500 events, RSS sampled
continuously at 20 Hz. Start 42.8867 MiB,
peak 44.2656 MiB, end 43.5273 MiB.
Window means 43.6961 ->
43.8469 MiB; drift
**0.345312%**, strict <5%: PASS.
Raw endpoint change 1.493761% is separately
reported and is not substituted for the specified matched-window drift.

External TCP was blocked in the verification process while loopback stayed
available: 0 external attempts. Fresh QCI-2
inference also ran with its existing external-network guard. No cloud service
is required; physical Wi-Fi/internet disconnect or OS firewall was not claimed.
The fixed-size state/outbox/audit limits and replay-retention contract are
documented. Source artifacts, profiles and terminal outputs are preserved.

## Tests and remaining CPU work

QCI-3: 67 collected, 67 passed,
0 failed, 0 skipped,
16.43 seconds.
Whole repository: 348 collected, 346 passed,
2 failed, 0 skipped,
114.31 seconds. The two unchanged CPU1 failures are
actual IR size <6.5 MB and test mAP drop <1 percentage point.

Actual IR 11,773,383 bytes; dense INT8 constants alone
11,119,984 bytes. Lossless zlib trial still exceeds
the budget. Requested NNCF INT4 compression retained all convolution groups
at INT8 and produced 11,757,999 bytes; it was not mislabelled or deployed.
Full bias correction used the same 300 training-only calibration samples;
validation mAP50 0.761794762
vs existing 0.762948771, so
the worse candidate was rejected without test-set selection.

Recorded current test mAP drop: 1.025514578 pp.
Fresh actual CPU inference: 30 warmups, 200 timed iterations, mean
169.227764 ms, P95 343.493200 ms, serial capacity
5.909196 FPS. This fails <20 ms and cannot
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
| Required feature branch used | PASS |
| QCI-2 event contract consumed | PASS |
| Pydantic v2 contracts implemented/reused | PASS |
| INFO tier implemented | PASS |
| WARNING tier implemented | PASS |
| CRITICAL tier implemented | PASS |
| Severity rules externally configurable | PASS |
| No invented class mappings | PASS |
| State machine implemented | PASS |
| Valid transitions tested | PASS |
| Invalid transitions handled | PASS |
| Event idempotency implemented | PASS |
| Critical siren triggers once per activation | PASS |
| Webhook client implemented | PASS |
| Webhook timeout implemented | PASS |
| Bounded retry policy implemented | PASS |
| Webhook failure does not crash local pipeline | PASS |
| Webhook-disabled mode works | PASS |
| Offline/local mode works | PASS |
| Local mock webhook tests pass | PASS |
| Concurrent events isolated | PASS |
| Resolved events cleaned/evicted | PASS |
| Bounded in-memory state implemented | PASS |
| Structured logging implemented | PASS |
| Structured JSON/Pydantic output implemented | PASS |
| Memory profile measured | PASS |
| Documentation completed | PASS |
| Proof-of-work generated | PASS |
| Dataset permission for current research use | PASS |
| Memory drift <5% | PASS |
| Automated QCI-3 tests 100% passing | PASS |
| Automated repository tests 100% passing | FAIL |
| PR opened | FAIL (user reports GitHub access revoked; no push/PR attempted) |
| QCI-3 OVERALL | FAIL (repository CPU acceptance gates and PR submission remain unmet) |

Artifacts: `qci3_summary.json`, `loopback_demo.json`, `memory_profile.json`,
`memory_samples.csv`, `cpu_acceptance_followup.json`, `cpu_bias_candidate.json`,
`pytest_output.txt`, `repository_pytest_output.txt`, `verification_terminal.txt`,
`fresh_classifier_terminal.txt`, `proof_of_work.png`, `review.html`, registry
evidence and the ignored backup `delivery_manifest.json`.
