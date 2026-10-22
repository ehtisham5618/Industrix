# FDD-1 release regression — PASS_WITH_EXCEPTIONS

Baseline `9759dc0` · candidate `88bf3e3` · 2026-10-22T16:58:19.466027+00:00 → 2026-10-22T17:09:37.238520+00:00

| Stage | Component | Status | Detail |
|---|---|---|---|
| full_test_suite | all | **BASELINE_FAILURE** | `{"exit_code": 1, "duration_s": 316.8, "totals": {"passed": 606, "skipped": 12, "failed": 2}, "collected": 620, "baseline_totals": {"passed": 593, "skipped": 11, "failed": 2}, "log": "reports\\fdd1\\pytest_candidate.txt"}` |
| model_regression | inference | **PASS** | `{"exit_code": 0, "duration_s": 151.7, "report_status": "UNDEFINED_THRESHOLD", "check_counts": {"PASS": 16, "UNDEFINED_THRESHOLD": 8}, "metrics": {"precision": 0.7293111176548043, "recall": 0.7802242886192703, "map50": 0.7819953253357151, "map50_95": 0.4917199666882641}, "delta_pp": {"precision": 0.131379, "recall": 0.002021, "map50": 0.029063, "map50_95": -0.021387}, "model_sha256": "c4aba081f6357` |
| live_stack_startup | watchdog+backend+dashboard | **PASS** | `{"duration_s": 14.1, "detail": {"backend": "healthy", "dashboard": "healthy"}}` |
| live_predict_contract | backend+inference | **PASS** | `{"detail": [{"fixture": "ife_ui3_fire.png", "http": 200, "detections": 3, "classes": ["fire", "smoke"]}, {"fixture": "ife_ui3_textile.png", "http": 200, "detections": 1, "classes": ["baekra"]}]}` |
| live_corrupt_upload | backend+preprocessing | **PASS** | `{"detail": {"http": 400, "body": "{\"detail\":\"Uploaded file is not a readable image.\"}"}}` |
| live_service_endpoints | backend+incidents+dashboard | **PASS** | `{"detail": {"health": {"http": 200, "bytes": 162}, "system_status": {"http": 200, "bytes": 1052}, "incidents": {"http": 200, "bytes": 78}, "dashboard": {"http": 200, "bytes": 2}}}` |
| live_dashboard_render | dashboard | **PASS** | `{"duration_s": 5.3, "log": "reports/fdd1/live_dashboard_render.txt"}` |
| load_and_memory_smoke | backend (resource) | **NOT_VERIFIED** | `{"reason": "short smoke: memory stability needs a long soak; no approved latency SLA", "detail": {"duration_s": 180.875, "attempted": 321, "failed": 0, "throughput_rps": 1.9953379953379953, "p50_ms": 860.1586895932617, "p95_ms": 2096.9414786514276, "rss_drift_percent": 3.744855601283544, "private_bytes_drift_percent": 7.537828629242236, "summary": "reports\\fdd1\\load\\20261022T170630Z-smoke\\summ` |
| no_unexpected_restarts_during_gate | watchdog | **PASS** | `{"detail": {"backend": 0, "dashboard": 0}}` |
| clean_shutdown | watchdog | **PASS** | `{"detail": {"watchdog_exit": 0, "ports_free": {"8000": true, "8501": true}}}` |
| physical_offline | system | **NOT_VERIFIED** | `{"reason": "no physical network disconnection; offline enforced by loopback-only config, socket guards and import checks"}` |

## Test suite by component

| Component | Passed | Failed | Errors | Skipped |
|---|---:|---:|---:|---:|
| CME_OPT1_Hard_Negative_Augmentation | 12 | 0 | 0 | 0 |
| CME_OPT2_Model_Fine_Tuning | 6 | 0 | 0 | 0 |
| Confidence_Calibration | 7 | 0 | 0 | 0 |
| EAP_1_LowLight_IR_Robustness | 41 | 0 | 0 | 0 |
| EAP_2_CI_Model_Regression | 29 | 0 | 0 | 0 |
| EAP_3_Lightweight_Docker | 6 | 0 | 0 | 10 |
| EAP_4_Load_Test | 42 | 0 | 0 | 1 |
| EAP_5_Watchdog | 38 | 0 | 0 | 0 |
| ESE_CPU1_Quantization | 14 | 2 | 0 | 0 |
| FDD_1_Release_Regression | 13 | 0 | 0 | 1 |
| IFE_UI1_Streamlit_Console | 21 | 0 | 0 | 0 |
| IFE_UI2_Incident_Audit | 22 | 0 | 0 | 0 |
| QCI_3_Severity_IoT | 67 | 0 | 0 | 0 |
| QCI_4_Edge_Telemetry | 49 | 0 | 0 | 0 |
| QCI_5_Incident_PDF | 42 | 0 | 0 | 0 |
| SED_1_Multi_Camera | 28 | 0 | 0 | 0 |
| SED_2_Alert_Escalation | 35 | 0 | 0 | 0 |
| SED_3_Stress_Testing | 23 | 0 | 0 | 0 |
| tests | 111 | 0 | 0 | 0 |

## Failures

- BASELINE_FAILURE: `ESE_CPU1_Quantization.tests.test_quantization.MeasuredQuantizationAcceptance::test_actual_ir_size_below_6_5_decimal_mb` (baseline: failed)
- BASELINE_FAILURE: `ESE_CPU1_Quantization.tests.test_quantization.MeasuredQuantizationAcceptance::test_actual_map_drop_below_one_percentage_point` (baseline: failed)
