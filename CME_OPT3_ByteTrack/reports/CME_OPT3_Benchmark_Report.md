# CME-OPT3 Benchmark Report

**CME-OPT3 OVERALL: FAIL**

Completed evidence generated at 2026-10-04T23:54:56.418892+05:00. Original Oct1 deadline was missed; no earlier completion date is claimed.

ByteTRACK is integrated into Backend/main.py and the existing SED-1 scheduler. The existing CME-2 confidence calibration remains; its class-level 3-of-5 temporal stage is replaced by camera/class/track/geofence confirmation. Confirmed violations enter the existing SED-2 severity and mock-action engine; candidates never do.

## Detector and configuration

Detector: `cme-opt2-focal-cosine-12class-v1`, `Backend/best.pt`, SHA256 `c4aba081f6357e23a7370a5f7cf98eff2c6faa0c4c20a2d4dcb8bcabdd490061`. All12 names: ['baekra', 'color issues', 'contamination', 'cut', 'gray stitch', 'selvet', 'stain', 'chemical hazard', 'fire', 'no helmet', 'smoke', 'water leak']. No YOLO training or detector changes were made. The CME-OPT2 chemical shortfall remains a known limitation.
Runtime: {'python': '3.11.12', 'ultralytics': '8.4.24', 'torch': '2.10.0+cu128', 'cuda': '12.8', 'gpu': 'NVIDIA A10'}. Tracker: documented `BYTETracker.update`, `Backend/configs/bytetrack.yaml`, SHA256 `9037c64725a4c36910eb7aebd2801ea12360807055d7cbba92ae735002351f87`; lap0.5.13. Separate camera and class tracker instances preserve shared detector batching. No unsupported person/machinery classes are invented.

## Temporal logic

CANDIDATE → CONFIRMED on exactly15 observed consecutive evaluated frames → ACTIVE → CLEARED/EXPIRED. Missing detections reset candidate streaks, including ByteTRACK internal lost states. Raw sampled frame gaps are not positive evaluations. IDs/classes/cameras/geofences never share streaks. One formal event is emitted; active updates preserve its incident ID. Candidate state expires after existing clear_frames5; SED-2 resolves absent formal events under its existing 5/6-second policy. End/restart/loop boundaries clear stream state. Cleared identities are removed from the active map and archived by SED-2.

At the new Backend stream sampling target10FPS, 15/fps is1.5seconds; first-to-fifteenth observation span is1.4seconds. Target is not achieved automatically: source, evaluated-media and measured processing rates are separate. Existing direct SED-1 configurations at5FPS cannot meet2seconds with15frames. The CPU CLI smoke reached2.13FPS and cannot demonstrate live2second latency.

## Factory benchmark and independent truth

[Source and licensing](https://commons.wikimedia.org/wiki/File:Twentse_textielindustrie-948017.ogv): Twentse textielindustrie, NOF/NIAM / Netherlands Institute for Sound and Vision,1949, [CC BY-SA3.0NL](https://creativecommons.org/licenses/by-sa/3.0/nl/deed.en). Original687.68seconds; first continuous600seconds transcoded to H.264 CRF18 for codec compatibility, with no looping or montage. It includes transport/exterior/title shots as well as factory-floor operations. This is historical edited factory footage, not modern CCTV.
Actual ignored derivative: `data/test_factory_clip.mp4`, SHA256 `6a79429f1fceced1560aa446bbdd17fd2b46ab6622f98156e7a94082f94eb67c`; source SHA256 `4e5369991497dd232868a82ad167f79ce9ce8e3e0c02a28d3ad6a3531a4780ff`. Ground truth: `annotations/factory_events.csv`, SHA256 `045ea0721c68fefdc22fd482e48b676fa28fadf2d3f7ff3d2e0aaed816c4c2a5`.
Seventeen scene-level no-helmet intervals were independently visually reviewed using five-second contact sheets and one-second views around worker intervals, before the model benchmark. They mean visible factory workers without hardhats under the demonstration class policy; historical PPE mandates are not established. Cloth caps are not hardhats. Source interval onsets have up to1second uncertainty. Conservative latency includes that uncertainty; it is not hidden. No chemical spill, fire or water leak was independently verified; normal chimney exhaust is not an annotated safety event. Detector predictions are never used as truth.
Baseline is the actual existing calibrated CME-2 3-of-5 policy, not immediate detections-as-alerts. Both paths use identical predictions, checkpoint, resolution640, class thresholds, full-frame geofence, cadence and SED-2 rules. Formal transition alerts are counted, not repeated boxes/frames. Matching is same class with confirmation inside the verified event interval, zero temporal tolerance; scene-level annotations allow multiple independently confirmed tracks within one event.

## Actual results

| Metric | Baseline | CME-OPT3 | Target | Result |
|---|---:|---:|---|---|
| Formal false alerts | 9 | 0 | — | Measured |
| False-alert reduction | — | 100.0 | >=40% | PASS |
| Mean true-alert delay | See CSV | None | <=2s | Context; missed events included separately |
| Maximum true-alert delay | See CSV | None | <=2s for every true event including uncertainty | FAIL |
| Processing capacity FPS | 132.62045038036004 | 125.20881784067403 | Sustain evaluated cadence | PASS |

SourceFPS=25.0; evaluatedFPS=10.0; frames=6000; theoretical15-frame duration=1.5s. Timing basis: Paced source occurrence times and actual monotonic confirmation clock. The measured factory-source run is paced for ten real minutes. Per-path performance capacity includes decoding/shared inference and that path's temporal/escalation work, excluding intentional pacing sleeps and startup warmup.
Events=17, triggered=0, measured<=2s=0, conservative<=2s=0, missed=17. Trigger delay statistics: {'mean': None, 'p50': None, 'p95': None, 'max': None}. Empty delay statistics are unavailable, not zero or a pass.

| Event | Class | Start | Confirmation (wall clock) | Delay | <=2s measured | Missed |
|---|---|---:|---:|---:|---|---|
| factory-01 | no helmet | 151.0 |  |  | False | True |
| factory-02 | no helmet | 159.0 |  |  | False | True |
| factory-03 | no helmet | 169.0 |  |  | False | True |
| factory-04 | no helmet | 196.0 |  |  | False | True |
| factory-05 | no helmet | 209.0 |  |  | False | True |
| factory-06 | no helmet | 220.5 |  |  | False | True |
| factory-07 | no helmet | 244.3 |  |  | False | True |
| factory-08 | no helmet | 294.0 |  |  | False | True |
| factory-09 | no helmet | 334.0 |  |  | False | True |
| factory-10 | no helmet | 353.5 |  |  | False | True |
| factory-11 | no helmet | 414.0 |  |  | False | True |
| factory-12 | no helmet | 421.5 |  |  | False | True |
| factory-13 | no helmet | 458.0 |  |  | False | True |
| factory-14 | no helmet | 469.0 |  |  | False | True |
| factory-15 | no helmet | 524.0 |  |  | False | True |
| factory-16 | no helmet | 560.0 |  |  | False | True |
| factory-17 | no helmet | 573.3 |  |  | False | True |

## Tracking, memory and performance

Violation-state tracking counts: {'tracks_created': 34, 'tracks_confirmed': 0, 'candidate_tracks_expired': 34, 'tracks_cleared': 0, 'max_live_states': 2, 'live_states_at_video_end': 0, 'id_switches': None, 'fragmentation': None, 'live_states_after_cleanup': 0}. These are hazard candidate/event-state counts, not all detector object IDs. ID switches/fragmentation are unavailable without person/region MOT truth; no estimates are fabricated.
Performance: {'fps_before': 132.62045038036004, 'fps_after': 125.20881784067403, 'tracking_and_escalation_ms_per_frame': 0.48582660966717306, 'baseline_and_escalation_ms_per_frame': 0.03948387933344222, 'shared_inference_seconds': 39.513670795997726, 'decode_seconds': 5.491317226001231, 'actual_run_seconds': 599.93262049}. Confirmed/candidate state is bounded by currently tracked observations and configured absence expiry. Live state after cleanup=0; SED-2 active events after cleanup=0.

## Tests and multi-camera integration

Required suite `SED_2_Alert_Escalation/tests/test_tracker.py`:20tests PASS. Existing CME-2:7PASS; existing SED-1:7PASS; SED-2 including tracker:35PASS. Total49tests PASS. Real upstream ByteTRACK identities pass through the real SED-1 scheduler and SED-2 event metadata. A two-camera threaded scheduler smoke confirms independently. Tests also exercise low-confidence gating, lost detections, geofence exit, frame14/15 boundary, identity/class isolation, event recurrence, session reset, active-state removal and no premature Critical mock IoT action.
Dashboard minimally exposes track ID and configured candidate progress; ordinary image inference remains stateless and compatible. Stream/query/CLI defaults share one persistence constant. CLI smoke uses real YOLO/fire video and records95evaluations,1formal confirmation and persistent ID in `backend_smoke.json`.

## Definition of done and limitations

False-positive reduction>=40%: **PASS**. Every true event<=2seconds conservatively: **FAIL**. Required tests: **PASS**. Overall: **FAIL**.
A tracker cannot recover hazards that the detector never identifies or that fail calibrated confidence/strict consecutive observation. Missed events and domain shift remain visible; thresholds, annotations and persist_frames were not tuned after this benchmark to manufacture acceptance. A zero false-alert baseline cannot demonstrate40% reduction. A modern factory clip with precise operationally reviewed incident onsets remains needed for safety-generalization claims. There is no spatial fallback that joins unrelated IDs or counts missed detections as positives.

## Tracking and delivery

Policy `cmeopt3-bytetrack15-v1`; experiment `CMEOPT3-EXP-001`; MLflow `5c8e1a9a6e9840a4ac6c1e06489f442a` in the existing `Vision-Driven-Industrial-Safety` experiment, original CME-3 helper and persistent Modal tracking volume. Weights, videos and runtime caches stay outside Git.
GPU native idle scale-down600seconds/min_containers0 and the existing continuous-zero-utilization watchdog600seconds cover storage and inference under the same PID. Completed invocation ends immediately. Original deadline was already past; all execution dates are actual.

## Review artifacts

[False alerts and true-event recall graph](factory_alert_comparison.png); [per-class comparison](class_comparison.csv); [all event timings](per_event_latency.csv); [explicit 23-item checklist](Final_Validation_Checklist.md).

The baseline alerts cover 8 of 17 annotated scene events; the strict tracked path covers none. False-positive reduction alone does not establish a useful safety detector. The graph displays both counts together.
