# QCI-5 local incident PDF export

This task folder extends the existing incident PDF subsystem. It reads existing
legacy incidents or QCI-3 quality events, without writing another incident store.
The shared ReportLab service powers the existing CLI, FastAPI export route and
Streamlit incident-history download. See
[`docs/QCI_5_Incident_PDF_Report_Generator.md`](../docs/QCI_5_Incident_PDF_Report_Generator.md).

```powershell
$env:QCI5_CONFIG = 'QCI_5_Incident_PDF/configs/local_safe.json'
python Backend/scripts/export_incident_pdf.py --incident-id INC-2026-001
python -m pytest QCI_5_Incident_PDF/tests -q
```

Default output: `reports/incidents/<id>_incident_report.pdf`. An unknown ID fails
without creating a PDF. For existing QCI-3 events, select the quality event in
Incident History; its report ID encodes the complete source/event pair, avoiding
collisions. No model execution, GPU, runtime download or cloud request is needed.

Validation helpers (not production event producers):

```powershell
python -m QCI_5_Incident_PDF.verify demo
python -m QCI_5_Incident_PDF.verify profile
python -m QCI_5_Incident_PDF.capture_proof
```

The demonstration reuses QCI-3's already-recorded research event and its exact
original Event digest. Its original image and actual Grad-CAM overlay are
KolektorSDD noncommercial research/evaluation assets; the generated sample includes
attribution and license information. It does not assert a factory incident.
The live UI proof hosts the existing component in an isolated local harness.

Save/sync: exactly two task commits on `feature/sprint2-qci5-incident-pdf`.
After organization access returns:

```powershell
.\QCI_5_Incident_PDF\sync_when_access_returns.ps1
```

The helper uses a normal push, verifies the two-commit range, and preserves saved
work if remote access or history prevents syncing. Independent verified recovery
archives and their delivery manifest are under `backups/` (ignored by Git).
