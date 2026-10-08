# IFE-UI2 - local incident audit and PDF export

This task extends the existing `Backend/` and `Frontend/`. This separate folder
contains validation and offline-delivery tools, not another detector or alert
system. No detector weights, thresholds, ByteTRACK identities or 15-observation
confirmation rules are changed.

The active path is confirmed CME-OPT3 violation -> existing SED-2 event -> local
incident logger -> SQLite + native cropped JPEG -> shared ReportLab generator ->
CLI or Streamlit download. Candidate/raw/tracked-only detections are excluded.
The current upstream policy formally confirms safety classes; raw textile
quality detections do not become incidents unless upstream formally confirms
them. No new quality-confirmation or PDF-specific severity rule is invented.

## Start and export

Install `requirements.txt` in the existing backend environment, including
ReportLab, and `Frontend/requirements.txt` for the presentation process.
The existing machine uses Python 3.12 for inference and Python 3.14/Streamlit
1.63 for presentation. From repository root:

```powershell
ESE_CPU1_Quantization/runtime/venv/Scripts/python.exe -m uvicorn Backend.main:api_app --host 127.0.0.1 --port 8000
streamlit run Frontend/app.py --server.port 8501
```

Start three feeds as before. Incident History sits below the existing console.
Select an incident, expand **Evidence snapshot**, press **Export Incident PDF**,
then **Download Incident PDF**. The history is a Streamlit fragment, so its
controls do not rerun the monitoring console. Refresh clears previous PDF bytes;
incident changes invalidate prepared downloads. Every export generates fresh
PDF bytes; no PDF cache is used.

With the backend environment activated, the required CLI command is:

```powershell
python Backend/scripts/export_incident_pdf.py --incident-id INC-2026-001 --output reports/
```

The ID must already exist. `--database` and `--snapshots` optionally select an
isolated test store. Relative storage/output paths resolve against repository
root, not the caller's working directory. Unknown/invalid IDs and missing DBs
fail with non-zero status without creating an empty PDF. Output is atomically
replaced as `INC-2026-001_incident_report.pdf`. CLI and API share one generator.

## Storage and reliability

Default database: `Backend/data/events.db`; default evidence: `data/snapshots/`.
Override with `INCIDENT_DATABASE` / `INCIDENT_SNAPSHOTS` using local paths.
UNC paths, mapped network drives and URL storage/output destinations are rejected;
unverified/network storage also suppresses the console's 0% cloud claim.
Connections are per operation, WAL, foreign keys enabled, one-second busy
timeout. `BEGIN IMMEDIATE` serializes a durable per-year sequence and unique
source-event reservation. `INC-YYYY-NNN` expands beyond three digits as needed.

SED-2's short counters can restart. `source_event_key` combines camera, actual
CME UUID, SED-2 event ID and episode onset. One ongoing episode has one row;
resolved/recurrent episodes can create a new row. Original event/violation IDs
are retained separately. UTC timestamps distinguish episode onset, original
tracking confirmation, actual evidence frame and resolution observation.

Schema initialization preserves existing unrelated tables and incidents. A
newer or incompatible incident schema is rejected rather than deleted. No
retention purge is implemented. Tables: `incidents`, `incident_sequence`,
`incident_transitions`. Required fields, optional lineage, crop/hash metadata and
operator fields are documented in the measured report's actual schema table.

First persist a pending incident reservation, then write a JPEG to a temporary
file and replace atomically, then mark evidence ready in a short transaction.
This preserves the incident on snapshot failure without a false ready path.
Snapshot failures remain visible and retry on later observations. A 30-second
lease prevents duplicate writers and allows an abandoned pending reservation to
be retried after restart. Crop filenames use the validated incident ID and
sanitized camera/class. Native pixels get 10% padding per side and at least
64-pixel context where the frame permits; no enlargement. The source bbox and
actual crop rectangle are stored separately. SHA-256 is checked before PDF
embedding. Missing/corrupt evidence produces an explicit placeholder.

Logging runs after detector/tracker and display-hub locks are released. PDF
generation never runs in the detection callback. Storage errors are logged with
error type and source event, exposed in incident history, and do not terminate
inference. SQLite busy handling is bounded; active observations provide another
attempt. Persistently unavailable storage cannot guarantee lossless recording:
restore storage and inspect the reported failures. Confidence is the first
persisted confirmed observation, normally the confirmation frame, and is not
silently overwritten by later higher scores. Severity/resolution follow SED-2,
with transition history. Export reads incident data without changing it.

## Offline policy and report status

SQLite, snapshots, fonts, PDF and downloads are local. Dependency installation
is separate from offline operation. Streamlit analytics remains disabled.
`Backend/offline_policy.py` disables YOLO network probing/auto-install and applies
a process-only DECLINED consent adapter before OpenVINO imports. The installed
OpenVINO telemetry SDK otherwise attempted optional Google Analytics emission.
No user-wide consent file or SDK source file is changed. The adapter is validated
against the installed SDK; SDK upgrades must re-run the external-connection
guard. Other research scripts not importing Backend.main are outside this policy.

Reports are internal safety/quality audit records, not official OSHA 301 forms,
OSHA recordability determinations or ISO certification. Unknown injuries,
treatment, employee identity, signatures and corrective actions remain blank or
pending review. See [OSHA's recording criteria](https://www.osha.gov/laws-regs/regulations/standardnumber/1904/1904.7)
and [ISO's 45001 overview](https://www.iso.org/standard/45001). No standard text,
certification badge or regulator approval is reproduced.

Looped local-video feeds and controlled replay samples are flagged SAMPLE /
DEMONSTRATION. The sample uses a cropped container area from the existing hazmat
exercise clip and controlled detector outputs, then real ByteTRACK/SED-2. It is
not a real chemical spill or workplace injury. Unit/validation databases are
isolated under temporary directories or this task's ignored runtime folder.

## Validation

```powershell
ESE_CPU1_Quantization/runtime/venv/Scripts/python.exe -m IFE_UI2_Incident_Audit.run_checks
ESE_CPU1_Quantization/runtime/venv/Scripts/python.exe -m IFE_UI2_Incident_Audit.sample
ESE_CPU1_Quantization/runtime/venv/Scripts/python.exe -m IFE_UI2_Incident_Audit.validate
```

The sample command refuses an occupied sample database. Use a new fixture
directory via `create_sample()` if rebuilding, never overwrite a live DB.
Validation requires free ports 8000/8501, installed Edge/Playwright, pypdf and
local model/video artifacts. Run timed regression tests and performance checks
sequentially to avoid distorting their host-sensitive deadlines.

The validator blocks all Python core socket connections for replay/logging/crop/
PDF; a real backend rejects non-loopback TCP; a fresh browser blocks external
page requests. It tests real Streamlit downloads while three real CPU feeds run.
Twenty fresh service exports, cold CLI process time, API/Streamlit request-to-
bytes and actual browser click-to-frontend-bytes-ready are measured separately.
The last measure correlates browser `Date.now()` at the actual click event with
Python epoch at bytes readiness on the same machine. The broader Playwright
actionability/scroll-to-download-control interval is also retained, without
confusing it with PDF bytes readiness. A validation-only local timing journal
is enabled by `INCIDENT_UI_TIMINGS_PATH`; no epoch/debug fields enter the UI.

Evidence: `reports/sample_incident.pdf`, `reports/ife_ui2_metrics.json`,
`reports/ife_ui2_pdf_export_samples.csv`, `reports/ife_ui2_ui_export.png` and
`reports/IFE_UI2_Incident_Export_Report.md`. PDF pages are rendered locally and
visually inspected; render previews remain in ignored runtime storage.

## Two local commits and later sync

Branch `feature/atlantis-incident-pdf` starts from completed UI1 HEAD
`da109f0df0d95896e8013876c108812eda554c9f`. Exactly two new task commits retain
the previous dependency history. Author: `ehtisham5618`,
`ehtisham.malik5618@gmail.com`. The renamed origin is
`https://github.com/devlogixtechnology/industirx.git`.

No push or PR while access is revoked. Once access returns:

```powershell
git push -u origin feature/atlantis-incident-pdf
# Or use .\IFE_UI2_Incident_Audit\sync_when_access_returns.ps1
```

No force push is used. Ignored `backups/` contains a verified complete-history
Git bundle and local runtime ZIP. Database recovery copies use SQLite's online
backup API, including committed WAL changes, not an unsafe live-file copy.
Models, clips, local MLflow and required demonstration snapshots stay outside Git.
Restore into a new folder, extract the runtime archive, recreate environments,
and set the clone's origin to the organization URL before syncing.
