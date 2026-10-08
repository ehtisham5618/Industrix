# Sprint 4 CPU integration - release candidate

Target `v0.4.0-sprint4-cpu-ready` is **pending**, not a created release.

- Existing CME-OPT1 augmentation and CME-OPT2 focal/cosine YOLOv8s checkpoint
  remain unchanged; the detector exposes the verified 12-class map.
- CME-OPT3 ByteTRACK supplies camera-scoped identities and strict 15 evaluated
  observations before formal hazard confirmation, with SED-2 severity rules.
- ESE-CPU1 selected INT8 OpenVINO artifacts run on CPU. The FP16 ONNX artifact
  remains available; neither model nor deployment artifacts are rebuilt here.
- ESE-CPU2 uses three independent paced local-video captures, a ring of 15 raw
  frames, every-fourth-frame eligibility and fair shared inference scheduling.
- ESE-CPU3 retains genuine 60-minute stress evidence. Its approximately 2.45
  evaluated FPS and the CPU1 size/accuracy/latency shortfalls remain unresolved.
- IFE-UI1 presents actual live feeds, CPU/RSS/FPS and local processing status.
  Integration fixes add actual rolling inference mean/P95, verified model class
  count, software-only relay status and retained CONFIRMED labels for active tracks.
- IFE-UI2 stores incident metadata, original cropped evidence and lifecycle
  updates in local SQLite and generates fresh local ReportLab PDF downloads.
- IFE-UI3 packages real-model E2E tests, offline guarded startup/restart,
  deterministic labelled footage, real browser recording and measured reports.

Known limits: no forklift-proximity class/rule, no physical RTSP/USB feeds in
this demo, repeated training-image fixtures do not validate generalization,
no physical WiFi-disconnect verification, original numerical performance gates
remain failed, authenticated video upload unavailable, organization repository
access revoked, merge/release governance pending.

After access returns, push the saved feature branch and submit the prepared PR.
Do not bypass reviewers or branch protection. After an approved merge, confirm
the merged commit and that the tag does not exist, then a permitted maintainer
can run:

```powershell
git fetch origin --tags
# Set this only to the verified approved merged commit, never the feature HEAD.
$mergedCommit = '<verified-approved-merged-commit>'
git tag -a v0.4.0-sprint4-cpu-ready $mergedCommit -m 'Sprint 4 CPU-ready release'
git push origin v0.4.0-sprint4-cpu-ready
```

No tag is deleted, moved or created as part of the offline task delivery.
