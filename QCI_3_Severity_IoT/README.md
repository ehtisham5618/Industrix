# QCI-3 severity alarms and local IoT webhook

This task lives in its own folder inside IndusriX. It consumes actual QCI-2
normal/defect predictions, reuses SED-2 severity enums/engine, persists monotonic
activation state and audit, and dispatches Critical webhooks through a bounded
durable queue. The existing API and Streamlit monitor have small status bridges.

The default research configuration maps normal to INFO and defect to WARNING;
webhooks are disabled. Critical mappings are explicit research/demo rules.
No factory rule approval or physical siren verification is claimed.

See [the state-machine and run documentation](../docs/QCI_3_Severity_Alarm_State_Machine.md),
[dataset scope/attribution](LICENSE_DATA.md), and
[measured review evidence](../reports/qci3/QCI_3_Production_Review.md).

```powershell
& 'ESE_CPU1_Quantization/runtime/venv/Scripts/python.exe' -X utf8 -m pytest QCI_3_Severity_IoT/tests -q
& 'ESE_CPU1_Quantization/runtime/venv/Scripts/python.exe' -X utf8 -m QCI_3_Severity_IoT.verify
```

Required model/data stay in QCI-2/QCI-1 ignored runtime folders and verified local
archives. No GPU is required by this alarm layer. CPU recovery experiments stay
isolated in this task's runtime; unsuccessful candidates do not replace the
existing deployed detector.
