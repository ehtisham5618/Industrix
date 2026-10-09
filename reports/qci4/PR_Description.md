# QCI-4: add edge telemetry and graceful cloud failover

Real local resource/model/alarm health now feeds a typed cached API and the
existing monitor. Optional metadata sync survives cloud outages using bounded
SQLite storage, device-specific immutable dedupe identities, ordered replay,
matched acknowledgements and managed background workers. Local prediction and
alarm processing never call cloud synchronization.

Default cloud/metadata permissions are disabled. No production endpoint is
invented; the explicit local mock contract covers outage/restart/429/500/timeout,
source identity, capacity, privacy and recovery. No images or model weights leave
the gateway. Evidence and inherited acceptance failures are reported explicitly.

QCI-4 — EOD Update
Status: local edge telemetry/failover implementation verified; unrestricted release gates unmet.
Branch: feature/sprint2-qci4-edge-telemetry-failover
Telemetry: real CPU/RAM/disk/process, QCI-2 and QCI-3 health; default 2s bounded sampler.
Cloud: disabled by default; metadata opt-in only; strict health/ack/timeouts/retries.
Outage: 12 fresh local predictions/CAM outputs; local alerts retained.
Recovery: 18 event summaries, zero duplicate logical delivery; critical/resolved order verified.
Memory: 1.297255% matched-window drift, strict <5% PASS.
Tests: QCI-4 49/49 PASS; repository 395/397.
PR: deferred, access revoked; two local commits with verified cold-clone/runtime backup and future normal push helper.
Blockers: existing CPU1 size/accuracy gates; no production cloud endpoint/vendor contract supplied (mock validation complete).

Evidence: reports/qci4/QCI_4_Production_Review.md and qci4_summary.json.
