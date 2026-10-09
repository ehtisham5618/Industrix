# QCI-5 Incident PDF Report Generator

## Objective and architecture

Existing persisted incident/event -> read adapter -> Pydantic v2 ReportData ->
bounded local evidence preparation -> ReportLab A4 -> parser validation -> atomic
file -> CLI or existing API/UI download. There is no new incident database, model
inference, GPU allocation, cloud integration or event policy change.

## Authoritative data

Legacy `Backend.incidents.repository.IncidentRepository` remains authoritative for
`INC-YYYY-NNN` hazard incidents and their native snapshot hashes. QCI-3's existing
`qci3_events` and `qci3_audit` tables provide quality classification, recorded
severity/state, model/policy, transition history and actual delivery enum. A
canonical URL-safe ID encodes `[source_id,event_id]`; it avoids basename/event-ID
collisions. The source/event identity is checked against the stored status.
No severity is recalculated, and no bounding box is invented for classification.
SQLite reads use a short read snapshot and explicitly close before PDF rendering.
The quality listing limits rows and hashes the complete stored status for UI cache
invalidation, including delivery acknowledgements without new observations.

## Contracts and local configuration

`ReportData` requires incident/event IDs, an aware UTC timestamp, class, one of the
existing severity enum values and state. Confidence is finite and in [0,1].
Optional evidence, meaningful bbox/track, operator fields and telemetry are typed.
Notes/actions up to 100,000 characters are fully wrapped; larger inputs fail
validation instead of silently truncating. History has an explicit 200-transition
limit with a visible warning when exceeded. Evidence is limited to two images.
`ExportResult` records SUCCESS/FAILED, ID, path, bytes, SHA-256, warnings, version,
lookup/evidence/render/write/total milliseconds and a controlled error category.

Set `QCI5_CONFIG` to `QCI_5_Incident_PDF/configs/local_safe.json` or another trusted
local JSON config (<=64 KiB). Defaults: `reports/incidents`, A4, `qci5-report-v1`,
heatmaps and telemetry included when available. `quality_database` overrides the
QCI-3 store; otherwise QCI3_CONFIG's database is honored, then the existing default
`Backend/data/events.db`. `evidence_roots` explicitly authorize local directories;
legacy snapshots also use the repository's own verified root. No secrets belong
in this config. UNC/mapped network storage, URLs and parent traversal are rejected.
CLI `--output` is an explicit trusted local root, not an API-controlled path.

## Layout and typography

A4, 18 mm side/top margins, 25 mm bottom margin, 10 pt body/15 pt leading and
12 pt section headers. ReportLab's bundled local Vera fonts provide suitable
Latin/Greek/Cyrillic glyphs. Unsupported glyphs display an explicit `[U+XXXX]`
code point with a warning. No font or logo download occurs. User metadata is
XML-escaped. Tables split and notes flow across pages; there is no blanket font
shrink or hidden truncation. Footer: local-generation note, report ID, page and
version. PDF metadata names IndusriX, with no invented employee identity.

Sections: title/generated timestamp/version; incident identity/severity/state;
source/location/sample; actual classification/confidence/model/policy; meaningful
bbox/track when recorded; original/crop and Model Attribution Heatmap; retained
alarm transitions and delivery; optional timestamped edge telemetry; operator
review/signature/date/comments/corrective action; internal-review note; warnings.
The report makes no ISO certification, OSHA approval or root-cause claim.

## Evidence and provenance

Original images are never modified. Reads are limited to 16 MiB/image and decode
to at most 16 million pixels. Embedding uses a local <=1200x1200 RGB JPEG copy,
preserves aspect ratio and fits available width/100 mm height. Buffers/images
close using context managers. Native Pillow decoding bypasses the existing
Ultralytics install-on-corrupt-image wrapper without changing global Pillow.
Missing, corrupt, oversized, integrity-mismatched or out-of-root evidence becomes
an unavailable section with EVIDENCE_MISSING/INVALID warning, not a failed report.

QCI-3 does not persist arbitrary image paths or full prediction objects. Therefore
there is no filename-based image inference. A trusted optional `evidence_index`
(<=1 MiB, <=100 entries, <=2 images/entry) binds each report ID to the exact stored
Event digest and SHA-256 of each original/overlay. A stale or malformed binding is
rejected with a warning. Example structure, describing real files only:

```json
{
  "<canonical QCI3 report ID>": {
    "event_digest": "<actual stored SHA-256>",
    "is_sample": true,
    "evidence": [{"role": "Evidence image", "path": "<allowed local path>",
                  "sha256": "<actual source SHA-256>",
                  "context": "<recorded acquisition context>"}]
  }
}
```

The public research sample uses the existing `demo.critical / actual-2` record.
The verifier reconstructs the original Event from the existing QCI-3 prediction
and confirms its digest before binding curated `test/kos18/Part3` and the real
Grad-CAM overlay. It is labelled SAMPLE / DEMONSTRATION; image acquisition time
is unavailable. Dataset attribution/license are included in the PDF. See
`QCI_3_Severity_IoT/LICENSE_DATA.md` for the noncommercial research permission.

## Severity, delivery and telemetry

Severity/state are exact stored QCI-3 values. ACKNOWLEDGED means receiver delivery,
and does not assert a physical siren activation. A resolved record remains
resolved in its report. Legacy records preserve their existing SED-2 rating.
QCI-4 is read only when an existing monitor has a sampled snapshot; export never
starts its sync worker. Telemetry is labelled `Telemetry at report generation
time` with its actual sample timestamp, never relabelled as incident-time data.
The sample verifier obtains genuine local measurements through the QCI-4
collector with cloud disabled and stops it. A cold CLI with no monitor reports
telemetry unavailable. Empty operator fields remain blank/pending review.

## CLI and download

```powershell
python Backend/scripts/export_incident_pdf.py --incident-id INC-2026-001
python Backend/scripts/export_incident_pdf.py --incident-id <QCI3-ID> --quality-database <existing.db> --output reports/incidents
```

The existing `POST /incidents/{incident_id}/export` returns `application/pdf`, a
safe attachment filename, no-store/nosniff and report-version/generation-time
headers. No duplicate export route exists. The existing list adds bounded
`quality_incidents`, and Incident History offers Export then Download Incident PDF
using Streamlit's local download component. One current PDF is cached per session,
keyed by backend/ID/status revision/report version; refresh clears it. The API
uses only service-generated files, accepts no filesystem download parameter, and
quality detail omits evidence paths. Existing trusted local application access
policy is unchanged; exposure beyond that boundary needs the application's
deployment authentication policy.

## Atomic output, concurrency and errors

Deterministic safe filenames, bounded Windows filename length (full ID inside the
PDF), resolved root containment, unique temporary files, fsync, atomic replace.
Failure removes its own temporary file and leaves any previous valid report.
64 fixed lock stripes serialize same-ID writers without an unbounded lock map.
Windows sharing errors have eight bounded 20 ms replace attempts. No local-render
network timeout is introduced. Final bytes are checked for PDF signature, size,
parser validity, identity and severity before publication. PdfReader is explicitly
closed to clear parsed object graphs. After rendering, the production service
explicitly collects unreachable PDF cycles after its inner renderer has released
locals. This runs for every export, including errors, and its cost is included
in render/total latency; it is not a benchmark-only memory adjustment.
Structured logs identify starts/completion,
failure category, evidence warning and latency without image content/operator
notes. API errors use 404/422/503 and controlled codes; internal traces are not
shown to operators.

## Offline, performance, memory and tests

`verify demo` guards lookup, evidence, rendering and existing FastAPI ASGI download
against all socket connects. Windows' event-loop socket pair is constructed before
the guard. The real CLI subprocess is also guarded. The live Streamlit harness
uses loopback-only API TCP and a fresh browser blocking external page requests.
ReportLab and pypdf require no runtime assets from the internet.

`verify profile` continuously samples process RSS at 20 Hz during 500 exports of
the same real record with two genuine images: 50 warmup, two equal 225-export
windows. Drift is absolute difference between window means / first mean, strictly
<5%. Raw start/peak/end and endpoint change are also reported; allocator warmup
is not silently replaced with stable-window values. The profile uses the same
per-export cycle cleanup as production; it adds no profiling-only garbage
collection or retained PDF-byte cache. Latencies separately record lookup, evidence,
render plus parser validation, write and total; no new numeric SLA is invented.

Run `python -m pytest QCI_5_Incident_PDF/tests -q`. Required behavior tests include
metadata/severity/confidence, missing records, contract failures, real/absent/bad
images, integrity/pixel/byte/root limits, heatmap label, multi-page long notes,
Unicode/markup, telemetry-time distinction, offline API/MIME, CLI, concurrency,
atomic failure recovery, stale evidence and delivery-aware cache invalidation.
Full-suite historical CPU1 acceptance failures remain visible and unchanged.
Both dependency files constrain Starlette to `>=0.46,<1` because the existing
application uses app-level lifecycle hooks removed in Starlette 1.0. The actual
validated package versions are recorded with the review evidence; no lifecycle
or model-policy rewrite is included.
Measured results and DoD: `reports/qci5/QCI_5_Production_Review.md` and
`qci5_summary.json`; actual PDF `sample_incident_report.pdf`, page PNGs, live UI
screenshot, raw test output and continuous memory CSV are saved beside them.

## Limitations and delivery

Historical events without recorded evidence cannot gain inferred or invented
images. The 200-row timeline shows retained history only, not an infinite audit.
Research severity overrides and tiny-test classifier results are not factory
policy approval. The task is local, and no imagery/report is uploaded externally.
Two local commits and verified history/runtime backups permit a normal future
push when organization access returns. Full repository release and PR review
status are reported separately from local QCI-5 feature acceptance.
