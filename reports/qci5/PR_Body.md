# QCI-5: add downloadable local incident PDF reports

Consume the existing local incident/QCI-3 stores through a validated adapter and
the shared ReportLab A4 service. The existing CLI and incident export API/UI now
support quality events, real evidence/Grad-CAM, recorded severity/delivery and
timestamped optional telemetry. Missing or corrupt evidence produces a warning;
safe filenames, bounded buffers and atomic writes protect exports.

QCI-5 — EOD Update

Status: Local reporting acceptance PASS; full-repository/review gates unmet.
Branch: feature/sprint2-qci5-incident-pdf; implementation 703e1c8f5a05ee7d5f8e3ca0606e76a9dcb292b2.
Incident source: existing QCI-3 SQLite, demo.critical / actual-2; original Event digest verified.
ReportLab PDF: qci5-report-v1, A4, 4 pages, 250787 bytes, real image + Grad-CAM.
Download integration: existing POST /incidents/{id}/export and live existing Streamlit component verified.
Offline: 0 attempted socket connects for guarded export/API/CLI; no runtime downloads/GPU.
Performance: mean 483.620, P50 383.466, P95 1022.003, max 3060.642 ms.
Memory: 1.449849% matched-window drift, strict <5% PASS, 500 exports.
Tests: QCI-5 42/42 PASS; root 437 pass/2 inherited CPU1 failures.
PR: deferred per revoked-access/local-commit instruction; no PR URL claimed.
Blockers: existing CPU1 size/mAP release gates and organization repository access.
Evidence: reports/qci5/sample_incident_report.pdf, QCI_5_Production_Review.md, qci5_summary.json, raw test/RSS/UI proof.
Delivery: exactly two local commits plus verified recovery archives; sync_when_access_returns.ps1 for normal future push.

No imagery/report is uploaded externally. The sample is an explicitly labelled
KolektorSDD noncommercial research demonstration, bound to the original Event
digest. Full-system release remains conditional on the preserved CPU1 failures
and peer review. This body is prepared locally; no PR has been opened.
