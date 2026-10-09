# QCI-3: add severity state machine and IoT siren webhook

QCI-2 normal/defect outputs now feed validated, monotonic local severity states
and a durable Critical outbox. Duplicate observations do not repeat actions;
network failures preserve local Critical state. The existing API/monitor show
state, last transition and acknowledged/failed/unknown delivery.

Default research policy is normal INFO / defect WARNING with webhook disabled.
Critical is explicitly configured in the local software demo. HTTP has bounded
timeouts/retries and requires a matched receiver acknowledgement and stable
Idempotency-Key. No production secrets or hardware actuation are included.

QCI-3 — EOD Update
Status: Local research implementation verified; overall release gates unmet.
Branch: feature/sprint2-qci3-severity-iot-alerts
Severity: INFO/WARNING/CRITICAL, explicit research policy; monotonic state machine.
IoT: durable local outbox, bounded retries, 101 actual mock requests,
100 acknowledged activations, no duplicate activations.
Offline: external TCP blocked; localhost enabled; no required cloud/GPU.
Memory: 0.345312% matched-window drift, <5% PASS.
Tests: QCI-3 67/67 PASS; repository 346/348.
Dataset: noncommercial research/evaluation confirmed; publisher-license attribution recorded.
PR: not submitted, access revoked; exactly two local commits and verified future-sync backup.
Blockers: unchanged dense YOLOv8s CPU size/accuracy/throughput gates; factory rule approval only if later deployed.

Evidence: reports/qci3/QCI_3_Production_Review.md and qci3_summary.json.
