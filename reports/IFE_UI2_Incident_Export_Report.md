# IFE-UI2 incident export implementation and benchmark report

Execution **COMPLETED**; acceptance **PASS**.

## Objective and architecture

Confirmed CME-OPT3 violation -> existing SED-2 severity event -> incident logger -> local SQLite and unannotated native crop -> one ReportLab generator -> CLI or Streamlit download. Raw/candidate detections are excluded. Existing detection/tracking thresholds are preserved.

## SQLite schema

Production DB `Backend/data/events.db`; validation DB `IFE_UI2_Incident_Audit\runtime\demo_v2\events.db`. SQLite 3.45.3; journal mode **WAL**. Tables: `incidents, incident_sequence, incident_transitions`.

| Column | SQLite type |
| --- | --- |
| id | INTEGER |
| incident_id | TEXT |
| source_event_key | TEXT |
| event_id | TEXT |
| violation_id | TEXT |
| timestamp | TEXT |
| camera_id | TEXT |
| camera_location | TEXT |
| class_id | INTEGER |
| class_name | TEXT |
| confidence | REAL |
| severity | TEXT |
| bbox_x1 | REAL |
| bbox_y1 | REAL |
| bbox_x2 | REAL |
| bbox_y2 | REAL |
| coordinate_format | TEXT |
| image_width | INTEGER |
| image_height | INTEGER |
| track_id | INTEGER |
| geofence_id | TEXT |
| confirmation_frames | INTEGER |
| first_seen | TEXT |
| confirmed_at | TEXT |
| last_seen | TEXT |
| resolved_at | TEXT |
| snapshot_path | TEXT |
| snapshot_status | TEXT |
| snapshot_error | TEXT |
| snapshot_sha256 | TEXT |
| crop_rect | TEXT |
| snapshot_width | INTEGER |
| snapshot_height | INTEGER |
| evidence_frame_id | INTEGER |
| evidence_timestamp | TEXT |
| snapshot_lease_until | REAL |
| status | TEXT |
| created_at | TEXT |
| updated_at | TEXT |
| engine_version | TEXT |
| detector_version | TEXT |
| alert_policy_version | TEXT |
| is_sample | INTEGER |
| operator_name | TEXT |
| operator_notes | TEXT |
| corrective_action | TEXT |

Connections are per operation, busy timeout 1 s, WAL/foreign keys enabled. Durable yearly sequence and source-event UNIQUE constraint are reserved using BEGIN IMMEDIATE. Initialization preserves existing data, rejects incompatible/newer schemas, and never applies retention deletion.

## Confirmed-event integration

Actual controlled replay sample: **INC-2026-001**, SED-2 `SED2-000001`, tracking violation `CMEOPT3-f0150254d7724da9ba2203c77c1dbed1`, camera `camera_02` / Chemical Storage Bay, class `chemical hazard`, confidence 0.93, severity **WARNING**, track #1.
Sample timestamp UTC `2026-10-08T19:52:03.458799+00:00`. Observations 1-14 produced zero rows; observation 15 produced one, with 1 row after subsequent active observations. This is a controlled detector-output replay through real ByteTRACK, strict15 confirmation and SED-2, not an operational spill/injury. It uses the existing local hazmat exercise clip's container region at 20 s.

The source key includes actual camera, CME UUID, SED-2 episode ID and onset, preventing short counter reuse across restarts. Severity/resolution updates preserve the original confidence/crop and append transitions. New resolved/recurrent episodes receive new incidents. Current upstream quality detections without formal confirmation are not promoted into audit incidents.

## Snapshot logic

Default `data/snapshots/`; sample `INC-2026-001_camera_02_chemical_hazard.jpg` in isolated validation snapshots. Actual crop **507 x 278 native pixels**, source 1280 x 720; rect `[773, 430, 1280, 708]`. Padding 10% per side, minimum 64 px context where feasible, clipped to frame, no upscaling. JPEG quality 95; unannotated source pixels; SHA-256 `4dd87d12c66adb5de6c313eaa09dd101ffc88cf466ed2c87b3adbfa309270b5c`.

Transaction sequence: reserve pending row -> atomic JPEG write -> update evidence ready. Failures retain the incident with explicit evidence status. Pending snapshots have a 30 s claim lease; failed snapshots can retry on subsequent observations. Storage failures are visible and do not terminate inference. Permanently broken storage requires operator repair and may prevent recording; this is not described as lossless under unavailable storage.

## PDF layout

Shared generator `Backend/incidents/pdf.py`; CLI `Backend/scripts/export_incident_pdf.py`. Actual sample `reports/sample_incident.pdf`: 2 A4 pages, 44462 bytes, 1 embedded evidence image(s). Native local fonts, wrapping tables, clean page flow, page numbers, sample marking on every page, severity, identities, timeline, evidence, neutral description, sign-off and corrective/follow-up areas. Missing or integrity-failed images produce an explicit placeholder.

ISO 45001 / OSHA-oriented internal record only; not an official OSHA form, automatic recordability decision, or certification. No employee injury, treatment, signature or corrective action is invented. Reference context: [OSHA general recording criteria](https://www.osha.gov/laws-regs/regulations/standardnumber/1904/1904.7), [ISO 45001 overview](https://www.iso.org/standard/45001). No copyrighted standard text is reproduced.

## Offline operation

{'sqlite_write': True, 'snapshot_save': True, 'pdf_generation': True, 'streamlit_download': True, 'core_socket_connections_attempted': 0, 'external_browser_requests': [], 'backend_external_attempts': 0, 'method': 'All Python core sockets blocked; real backend forbids non-loopback TCP; browser blocks all non-loopback page HTTP requests. UI/API calls use only loopback.'}

All core socket connections were blocked for actual replay/logging/snapshot/PDF creation. The real backend rejected non-loopback TCP; browser external requests were blocked. The SDK analytics emitter found during audit is declined through a backend-process adapter before engine imports, without changing account-wide consent or SDK files. YOLO probing/auto-install and Streamlit usage analytics are disabled. Install dependencies separately before offline operation.

## Streamlit integration

Incident History follows the existing three-camera monitor. Selection and local evidence preview use bounded API routes. Export calls the same ReportLab service as CLI and exposes application/pdf with a validated deterministic filename. Downloads do not rerun the app. A fragment isolates history interactions; evidence decoding happens only while expanded. Changed incident data or Refresh invalidates prepared bytes. No cached PDF is used in fresh-generation benchmarks.

## PDF export performance

| Measurement | Count | Mean (s) | P50 (s) | P95 (s) | Max (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Fresh ReportLab service | 20 | 0.067766 | 0.060454 | 0.086730 | 0.106437 |
| API fresh generation (incl. query) | 5 | 0.182072 | 0.162572 | 0.257356 | 0.271377 |
| Streamlit request to bytes | 5 | 0.192321 | 0.170267 | 0.265579 | 0.278844 |
| Actual browser click to bytes ready | 5 | 0.294099 | 0.224973 | 0.416997 | 0.418041 |
| Playwright call to download control (incl. scrolling/rendering) | 5 | 0.705293 | 0.496870 | 1.146816 | 1.194628 |

Cold CLI complete process: 0.620396 s. Primary end-to-end target uses the actual browser click event to PDF bytes ready in the Streamlit process, correlated on this local machine. This includes dispatch/rerun, local HTTP, DB query and fresh generation; subsequent download-widget rendering and Playwright actionability/scrolling are separately reported. Epoch granularity is approximately 1 ms; clocks are the same host. All fresh bytes-ready samples must be <2.0 s.

| Run | Incident | Fresh service seconds |
| --- | --- | ---: |
| 1 | INC-2026-001 | 0.060196 |
| 2 | INC-2026-001 | 0.058019 |
| 3 | INC-2026-001 | 0.057234 |
| 4 | INC-2026-001 | 0.057692 |
| 5 | INC-2026-001 | 0.065444 |
| 6 | INC-2026-001 | 0.080006 |
| 7 | INC-2026-001 | 0.056957 |
| 8 | INC-2026-001 | 0.058699 |
| 9 | INC-2026-001 | 0.080176 |
| 10 | INC-2026-001 | 0.106437 |
| 11 | INC-2026-001 | 0.079156 |
| 12 | INC-2026-001 | 0.085430 |
| 13 | INC-2026-001 | 0.068091 |
| 14 | INC-2026-001 | 0.085693 |
| 15 | INC-2026-001 | 0.058582 |
| 16 | INC-2026-001 | 0.060712 |
| 17 | INC-2026-001 | 0.056194 |
| 18 | INC-2026-001 | 0.065509 |
| 19 | INC-2026-001 | 0.057119 |
| 20 | INC-2026-001 | 0.057982 |

## Tests and definition of done

Tests: `{'audit': {'tests': 22, 'passed': True}, 'cme2': {'tests': 7, 'passed': True}, 'sed1': {'tests': 28, 'passed': True}, 'sed2_and_bytetrack': {'tests': 35, 'passed': True}, 'ui1': {'tests': 21, 'passed': True}}`; local tracking run `cc24c160be4140b59416bc5b1fe55dd7`. Source implementation commit `c4db97954eab30ed1a8d533c80d87bee1cb0dde6`.

| Check | Result |
| --- | --- |
| Required Git branch used | PASS |
| SQLite incident database implemented | PASS |
| Schema contains required fields | PASS |
| Confirmed violations automatically logged | PASS |
| Unconfirmed detections are not logged | PASS |
| Incident logging is idempotent | PASS |
| Local snapshot generated | PASS |
| Bounding-box crop validated | PASS |
| Snapshot path stored in DB | PASS |
| ReportLab PDF generator implemented | PASS |
| CLI export command works | PASS |
| Incident metadata rendered in PDF | PASS |
| Evidence image embedded | PASS |
| Severity rendered | PASS |
| Operator sign-off section rendered | PASS |
| ISO/OSHA-oriented wording without false certification claims | PASS |
| Streamlit Export Incident PDF implemented | PASS |
| Fresh PDF bytes generation <2.0 seconds | PASS |
| PDF download works | PASS |
| 100% offline export path verified | PASS |
| No external network call required | PASS |
| Runtime DB excluded from Git | PASS |
| Operational snapshots excluded from Git | PASS |
| reports/sample_incident.pdf generated | PASS |
| Sample PDF included in evidence commit | PASS |
| Relevant tests passing | PASS |
| IFE-UI2 OVERALL | PASS |

## Evidence and delivery

`reports/sample_incident.pdf`, `reports/ife_ui2_metrics.json`, raw CSV exports, real browser screenshot, task regression terminals and this report. The sample PDF was generated by the real CLI/shared service and every final page was rendered and visually reviewed. Runtime databases/snapshots/model/video binaries stay ignored.

Exactly two new local commits on `feature/atlantis-incident-pdf`, based on completed UI1 `da109f0df0d95896e8013876c108812eda554c9f`. No push or PR while organization access is revoked. Verified bundle and SQLite-consistent runtime backup are local under this task. Later sync: `git push -u origin feature/atlantis-incident-pdf`. No history rewrite or force push.

Created: `Backend/incidents/`, offline policy adapter, export CLI, frontend incident history, task validation/tests/docs and measured reports/sample. Modified: Backend main, Frontend app/API client/dependency minimum, SED-2 optional lifecycle observer/resolution timestamp, root requirements/ignore rules and experiment tracking. Removed: none.
