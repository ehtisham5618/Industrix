# QCI-4 — Edge Telemetry & Graceful Cloud Failover

Local inference and QCI-3 alarms remain independent of optional cloud sync.
This separate task folder supplies real bounded telemetry, a typed cached API,
read-only alarm observation, durable bounded summary spooling, strict health/ack
checks, idempotent ordered recovery and managed worker shutdown.

Safe default: cloud disabled, neither metadata permission enabled, no endpoint,
no sync worker. No raw images, heatmaps, model weights or private names are sent.

See [run and architecture documentation](../docs/QCI_4_Edge_Telemetry_Cloud_Failover.md)
and [measured review evidence](../reports/qci4/QCI_4_Production_Review.md).
Dataset use remains the user-confirmed noncommercial research/evaluation scope;
the [publisher attribution notice](../QCI_3_Severity_IoT/LICENSE_DATA.md) applies.

```powershell
& 'ESE_CPU1_Quantization/runtime/venv/Scripts/python.exe' -X utf8 -m pytest QCI_4_Edge_Telemetry/tests -q
& 'ESE_CPU1_Quantization/runtime/venv/Scripts/python.exe' -X utf8 -m QCI_4_Edge_Telemetry.verify demo
& 'ESE_CPU1_Quantization/runtime/venv/Scripts/python.exe' -X utf8 -m QCI_4_Edge_Telemetry.verify profile
```

API: GET `/edge/status`, GET `/edge/history`. Production cloud endpoint/protocol
not provided; software localhost tests validate the explicit example contract.
The current deadline-bound connector requires numeric HTTPS IP endpoints and
Content-Length JSON; other vendor protocols need their documented adapter.
