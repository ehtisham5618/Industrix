# IFE-UI3: package Sprint 4 end-to-end CPU demo

The previously separate CPU capture, inference, tracking, escalation and incident
components now have reproducible local validation and a real HD operator walkthrough.
The package selects labelled deterministic footage while keeping the production
OpenVINO/ByteTRACK/15-observation/SED-2/SQLite/ReportLab pipeline unchanged.
Integration fixes keep active tracks labelled CONFIRMED, scale labels for tall
sources and display actual model class count, rolling inference timings and mock
relay status. Existing detector weights and calibrated thresholds are unchanged.

## Validation

`pytest tests/test_end_to_end_pipeline.py`: 5 passed, 0 failed,
0 skipped, 14.430s. Related functional total:
127 passed, 0 failures. The real selected CPU model is exercised; temporary
storage and an external-TCP guard make the E2E deterministic and local.
Actual guarded backend restart, three live sources, confirmation/escalation,
persistent native evidence and fresh Streamlit PDF download also pass.
Physical WiFi disconnection was not tested; guarded offline operation passed.

## Performance

CPU: Intel Core i5-7200U @ 2.50 GHz; 2 physical / 4 logical cores; Windows 11.

Warmed pre-recording operational aggregate: **6.529 evaluated FPS** over 20.219s, from completed-frame counter differences across all three sources.

Pre-recording pure inference rolling mean / P95: **145.072 / 180.993 ms**, latest 128 actual calls before browser capture.

During HD recording, actual rolling-five-second operational FPS averaged **1.657**, with P95 3.565. Aggregate canvas-update throughput: 1.629 FPS. These are processed/displayed frames, not 48 FPS model capacity.

Pure model inference mean / P95 at the end of recording: **502.068 / 1336.827 ms**, latest 128 actual OpenVINO calls, excluding preprocess/NMS. The mean of rolling mean readings over the recording was 489.751 ms; it is not pooled raw-call latency. Engine-capacity FPS was not remeasured.

System CPU mean / peak: **91.89% / 100.00%**. Backend RSS mean / peak: **579.20 / 581.55 MiB**. These include actual recording load; UI, recorder and other workstation processes contribute to system CPU.

Backend result-ready to canvas-update delivery mean / P95: **27.003 / 43.030 ms**, 204 acknowledged rendered frames. Clock alignment uses the lowest RTT midpoint; uncertainty 7.800 ms. This excludes capture/sampling/inference and does not measure physical screen paint.

Fresh PDF server generation: **242.764 ms**; frontend HTTP-to-bytes 249.269 ms; actual browser click-to-PDF bytes **0.380s**, below 2.0s.

Original CPU/model numerical gates remain failed; this demo does not requalify
size, accuracy, 16 ms latency or 48 FPS throughput.

## Recording and release

Actual 125.000s 1920x1080 MP4 was fully decoded and inspected;
metadata and hashes are in the integration report. Upload pending manual action;
no share URL yet. The repository organization has revoked access: this PR body
is prepared locally, with exactly two saved commits and verified recovery files.
PR creation, approved merge and `v0.4.0-sprint4-cpu-ready` tag remain pending.
Tagging an unmerged feature commit is not authorized.
