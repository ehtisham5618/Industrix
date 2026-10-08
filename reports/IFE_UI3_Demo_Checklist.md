# IFE-UI3 recording and release checklist

- [ ] Physical WiFi/internet disconnected - NOT PERFORMED; adapters remained up.
- [x] Both Python servers block non-loopback TCP; browser blocks external HTTP.
- [x] Backend startup and complete restart verified under guards.
- [x] Selected local OpenVINO INT8 CPU artifacts and 12 names verified.
- [x] Three real local feeds/capture sessions active through CPU2 ring15/sample4.
- [x] Actual ByteTRACK, candidate observations, strict15 and SED-2 verified.
- [x] Live Streamlit, real telemetry, readable labels and software-only relay.
- [x] Separate writable demo SQLite, native evidence and persistence after restart.
- [x] Fresh local ReportLab export and actual browser download under two seconds.
- [x] Required root E2E pytest passes; no skipped critical tests or failures.
- [x] Functional regressions pass; original hardware acceptance failures disclosed.
- [x] Actual 1920x1080 recording created and fully decoded/visually inspected.
- [x] No credential, private token or RTSP password appears in the walkthrough.
- [x] Runtime MP4/database/crops kept outside Git, with recovery archive.
- [x] Exactly two new local task commits and complete-history bundle verified.
- [ ] Upload - MANUAL ACTION REQUIRED; no share URL yet.
- [ ] PR creation/approved merge - pending restored organization access.
- [ ] Correct merged-commit release tag - NOT AUTHORIZED before approved merge.

See the measured integration report and backup delivery manifest for proof. This
checklist describes the final delivered artifacts; commit/archive checks are
confirmed during final delivery, not hardcoded as evidence in the readiness tool.
