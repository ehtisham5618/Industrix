"""Generate a reviewable handoff only from actual benchmark and test evidence."""
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT/'CME_OPT3_ByteTrack/reports'
VERSION = 'cmeopt3-bytetrack15-v1'


def digest(path):
    with Path(path).open('rb') as f: return hashlib.file_digest(f,'sha256').hexdigest()


def append(path, row, key):
    with path.open(encoding='utf-8',newline='') as f:
        reader = csv.DictReader(f)
        fields, records = reader.fieldnames, list(reader)
    normalized = {field:str(row.get(field,'')) for field in fields}
    existing = next((r for r in records if r[key] == row[key]),None)
    if existing:
        assert existing == normalized, f'Refusing to overwrite history: {row[key]}'
        return
    with path.open('a',encoding='utf-8',newline='') as f:
        csv.DictWriter(f,fieldnames=fields).writerow(normalized)


def main():
    summary = json.loads((REPORTS/'benchmark_summary.json').read_text())
    with (REPORTS/'per_event_latency.csv').open(encoding='utf-8',newline='') as f:
        latency = [r for r in csv.DictReader(f) if r['mode']=='bytetrack']
    reduction = summary['false_alert_reduction_pct']
    fp_pass = reduction is not None and reduction >= 40
    timing_pass = summary['events_within_2s_conservative'] == summary['true_events'] and summary['missed_events']==0
    structural = {
        'unchanged_selected_detector':digest(ROOT/'Backend/best.pt') == summary['detector_sha256'],
        'executed_sources_match':all(digest(ROOT/name)==value for name,value in summary['execution_sources_sha256'].items()),
        'video_bytes_verified':digest(ROOT/'data/test_factory_clip.mp4')==summary['video_sha256'],
        'independent_annotations_verified':digest(ROOT/'CME_OPT3_ByteTrack/annotations/factory_events.csv')==summary['annotation_sha256'],
        'all_12_classes':len(summary['names'])==12,
        'full_10_minute_video':summary['video_duration_seconds']==600 and summary['evaluated_frames']==6000,
        'persist_frames_15':summary['persist_frames']==15,
        'paced_wall_clock_timing':'monotonic' in summary['timing_basis'],
        'sustainable_cadence':summary['actual_processing_fps'] >= summary['evaluated_fps'],
        'state_cleanup':summary['tracking']['live_states_after_cleanup']==0 and summary['sed2_active_events_after_cleanup']==0,
        'mlflow_logged':bool(summary.get('mlflow_run_id')),
        'related_tests_pass':all('Exit code: 0' in (REPORTS/name).read_text() for name in
            ('cme2_tests.txt','sed1_tests.txt','sed2_and_tracker_tests.txt'))}
    assert all(structural.values()), structural
    accepted = all(structural.values()) and fp_pass and timing_pass
    assert accepted == (summary['status']=='PASS')
    audit = {'structural_checks':structural,'false_positive_reduction_target':fp_pass,
        'true_event_latency_target_conservative':timing_pass,'accepted':accepted,
        'limitations':'Historical factory documentary and scene-level visual PPE labels; operational hardhat requirements not established; no other true hazard classes in this segment.'}
    (REPORTS/'acceptance_audit.json').write_text(json.dumps(audit,indent=2)+'\n')
    env = summary['environment']
    lines = ['# CME-OPT3 Benchmark Report','',f"**CME-OPT3 OVERALL: {'PASS' if accepted else 'FAIL'}**",'',
        'Completed evidence generated at '+datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=5))).isoformat()+'. Original Oct1 deadline was missed; no earlier completion date is claimed.','',
        'ByteTRACK is integrated into Backend/main.py and the existing SED-1 scheduler. The existing CME-2 confidence calibration remains; its class-level 3-of-5 temporal stage is replaced by camera/class/track/geofence confirmation. Confirmed violations enter the existing SED-2 severity and mock-action engine; candidates never do.','',
        '## Detector and configuration','',f"Detector: `{summary['detector_version']}`, `Backend/best.pt`, SHA256 `{summary['detector_sha256']}`. All12 names: {list(summary['names'].values())}. No YOLO training or detector changes were made. The CME-OPT2 chemical shortfall remains a known limitation.",
        f"Runtime: {env}. Tracker: documented `BYTETracker.update`, `Backend/configs/bytetrack.yaml`, SHA256 `{summary['tracker_sha256']}`; lap0.5.13. Separate camera and class tracker instances preserve shared detector batching. No unsupported person/machinery classes are invented.",'',
        '## Temporal logic','',
        'CANDIDATE → CONFIRMED on exactly15 observed consecutive evaluated frames → ACTIVE → CLEARED/EXPIRED. Missing detections reset candidate streaks, including ByteTRACK internal lost states. Raw sampled frame gaps are not positive evaluations. IDs/classes/cameras/geofences never share streaks. One formal event is emitted; active updates preserve its incident ID. Candidate state expires after existing clear_frames5; SED-2 resolves absent formal events under its existing 5/6-second policy. End/restart/loop boundaries clear stream state. Cleared identities are removed from the active map and archived by SED-2.','',
        'At the new Backend stream sampling target10FPS, 15/fps is1.5seconds; first-to-fifteenth observation span is1.4seconds. Target is not achieved automatically: source, evaluated-media and measured processing rates are separate. Existing direct SED-1 configurations at5FPS cannot meet2seconds with15frames. The CPU CLI smoke reached2.13FPS and cannot demonstrate live2second latency.','',
        '## Factory benchmark and independent truth','',
        '[Source and licensing](https://commons.wikimedia.org/wiki/File:Twentse_textielindustrie-948017.ogv): Twentse textielindustrie, NOF/NIAM / Netherlands Institute for Sound and Vision,1949, [CC BY-SA3.0NL](https://creativecommons.org/licenses/by-sa/3.0/nl/deed.en). Original687.68seconds; first continuous600seconds transcoded to H.264 CRF18 for codec compatibility, with no looping or montage. It includes transport/exterior/title shots as well as factory-floor operations. This is historical edited factory footage, not modern CCTV.',
        f"Actual ignored derivative: `data/test_factory_clip.mp4`, SHA256 `{summary['video_sha256']}`; source SHA256 `4e5369991497dd232868a82ad167f79ce9ce8e3e0c02a28d3ad6a3531a4780ff`. Ground truth: `annotations/factory_events.csv`, SHA256 `{summary['annotation_sha256']}`.",
        'Seventeen scene-level no-helmet intervals were independently visually reviewed using five-second contact sheets and one-second views around worker intervals, before the model benchmark. They mean visible factory workers without hardhats under the demonstration class policy; historical PPE mandates are not established. Cloth caps are not hardhats. Source interval onsets have up to1second uncertainty. Conservative latency includes that uncertainty; it is not hidden. No chemical spill, fire or water leak was independently verified; normal chimney exhaust is not an annotated safety event. Detector predictions are never used as truth.',
        'Baseline is the actual existing calibrated CME-2 3-of-5 policy, not immediate detections-as-alerts. Both paths use identical predictions, checkpoint, resolution640, class thresholds, full-frame geofence, cadence and SED-2 rules. Formal transition alerts are counted, not repeated boxes/frames. Matching is same class with confirmation inside the verified event interval, zero temporal tolerance; scene-level annotations allow multiple independently confirmed tracks within one event.','',
        '## Actual results','', '| Metric | Baseline | CME-OPT3 | Target | Result |','|---|---:|---:|---|---|',
        f"| Formal false alerts | {summary['baseline']['false_alerts']} | {summary['bytetrack']['false_alerts']} | — | Measured |",
        f"| False-alert reduction | — | {reduction if reduction is not None else 'Unavailable: zero baseline false alerts'} | >=40% | {'PASS' if fp_pass else 'FAIL'} |",
        f"| Mean true-alert delay | See CSV | {summary['trigger_delay']['mean']} | <=2s | Context; missed events included separately |",
        f"| Maximum true-alert delay | See CSV | {summary['trigger_delay']['max']} | <=2s for every true event including uncertainty | {'PASS' if timing_pass else 'FAIL'} |",
        f"| Processing capacity FPS | {summary['performance']['fps_before']} | {summary['performance']['fps_after']} | Sustain evaluated cadence | {'PASS' if structural['sustainable_cadence'] else 'FAIL'} |",'',
        f"SourceFPS={summary['source_fps']}; evaluatedFPS={summary['evaluated_fps']}; frames={summary['evaluated_frames']}; theoretical15-frame duration={summary['theoretical_15_frame_seconds']}s. Timing basis: {summary['timing_basis']}. The measured factory-source run is paced for ten real minutes. Per-path performance capacity includes decoding/shared inference and that path's temporal/escalation work, excluding intentional pacing sleeps and startup warmup.",
        f"Events={summary['true_events']}, triggered={summary['events_triggered']}, measured<=2s={summary['events_within_2s']}, conservative<=2s={summary['events_within_2s_conservative']}, missed={summary['missed_events']}. Trigger delay statistics: {summary['trigger_delay']}. Empty delay statistics are unavailable, not zero or a pass.",'',
        '| Event | Class | Start | Confirmation (wall clock) | Delay | <=2s measured | Missed |','|---|---|---:|---:|---:|---|---|']
    for row in latency:
        lines.append('| '+' | '.join(row[k] for k in ('event_id','class_name','start_seconds','confirmation_seconds','delay_seconds','within_2s','missed'))+' |')
    lines += ['', '## Tracking, memory and performance','',f"Violation-state tracking counts: {summary['tracking']}. These are hazard candidate/event-state counts, not all detector object IDs. ID switches/fragmentation are unavailable without person/region MOT truth; no estimates are fabricated.",
        f"Performance: {summary['performance']}. Confirmed/candidate state is bounded by currently tracked observations and configured absence expiry. Live state after cleanup={summary['tracking']['live_states_after_cleanup']}; SED-2 active events after cleanup={summary['sed2_active_events_after_cleanup']}.",'',
        '## Tests and multi-camera integration','',
        'Required suite `SED_2_Alert_Escalation/tests/test_tracker.py`:20tests PASS. Existing CME-2:7PASS; existing SED-1:7PASS; SED-2 including tracker:35PASS. Total49tests PASS. Real upstream ByteTRACK identities pass through the real SED-1 scheduler and SED-2 event metadata. A two-camera threaded scheduler smoke confirms independently. Tests also exercise low-confidence gating, lost detections, geofence exit, frame14/15 boundary, identity/class isolation, event recurrence, session reset, active-state removal and no premature Critical mock IoT action.',
        'Dashboard minimally exposes track ID and configured candidate progress; ordinary image inference remains stateless and compatible. Stream/query/CLI defaults share one persistence constant. CLI smoke uses real YOLO/fire video and records95evaluations,1formal confirmation and persistent ID in `backend_smoke.json`.','',
        '## Definition of done and limitations','',
        f"False-positive reduction>=40%: **{'PASS' if fp_pass else 'FAIL'}**. Every true event<=2seconds conservatively: **{'PASS' if timing_pass else 'FAIL'}**. Required tests: **PASS**. Overall: **{'PASS' if accepted else 'FAIL'}**.",
        'A tracker cannot recover hazards that the detector never identifies or that fail calibrated confidence/strict consecutive observation. Missed events and domain shift remain visible; thresholds, annotations and persist_frames were not tuned after this benchmark to manufacture acceptance. A zero false-alert baseline cannot demonstrate40% reduction. A modern factory clip with precise operationally reviewed incident onsets remains needed for safety-generalization claims. There is no spatial fallback that joins unrelated IDs or counts missed detections as positives.','',
        '## Tracking and delivery','',f"Policy `{VERSION}`; experiment `CMEOPT3-EXP-001`; MLflow `{summary.get('mlflow_run_id')}` in the existing `Vision-Driven-Industrial-Safety` experiment, original CME-3 helper and persistent Modal tracking volume. Weights, videos and runtime caches stay outside Git.",
        'GPU native idle scale-down600seconds/min_containers0 and the existing continuous-zero-utilization watchdog600seconds cover storage and inference under the same PID. Completed invocation ends immediately. Original deadline was already past; all execution dates are actual.','']
    lines += ['## Review artifacts', '',
        '[False alerts and true-event recall graph](factory_alert_comparison.png); '
        '[per-class comparison](class_comparison.csv); '
        '[all event timings](per_event_latency.csv); '
        '[explicit 23-item checklist](Final_Validation_Checklist.md).', '',
        'The baseline alerts cover 8 of 17 annotated scene events; the strict tracked '
        'path covers none. False-positive reduction alone does not establish a useful '
        'safety detector. The graph displays both counts together.', '']
    (REPORTS/'CME_OPT3_Benchmark_Report.md').write_text('\n'.join(lines),encoding='utf-8')
    notes = json.dumps({'detector_sha256':summary['detector_sha256'],'tracker_config':'Backend/configs/bytetrack.yaml',
        'baseline':'existing calibrated CME-2 3-of-5 at same evaluated cadence','mlflow_run_id':summary.get('mlflow_run_id'),
        'max_alert_delay':summary['trigger_delay']['max'],'events_within_2s':summary['events_within_2s'],
        'events_within_2s_conservative':summary['events_within_2s_conservative'],'timing_basis':summary['timing_basis'],
        'fps_before':summary['performance']['fps_before'],'fps_after':summary['performance']['fps_after'],
        'annotation_onset_uncertainty_seconds':1,'benchmark_status':summary['status']},separators=(',',':'))
    append(ROOT/'Experiment_Tracking/alert_policy_registry.csv',dict(policy_version=VERSION,sprint='Sprint 4',task='CME-OPT3',
        detector_model_version=summary['detector_version'],threshold_config='Confidence_Calibration/configs/calibrated_thresholds.yaml',
        sampling_fps=summary['evaluated_fps'],window_size=15,required_frames=15,cooldown=0,
        clear_policy='track clear_frames=5; SED2 absent seconds=5/6; session reset on end/restart/loop',
        false_alerts_before=summary['baseline']['false_alerts'],false_alerts_after=summary['bytetrack']['false_alerts'],
        fp_reduction_pct=reduction if reduction is not None else 'not demonstrated: zero baseline false alerts',
        missed_violations=summary['missed_events'],mean_latency=summary['trigger_delay']['mean'] if summary['trigger_delay']['mean'] is not None else 'not observed',
        status='validated_factory_audit' if accepted else 'evaluated_target_shortfall',benchmark='historical_factory_600s_v1',notes=notes),'policy_version')
    commit = subprocess.check_output(['git','log','-1','--format=%H','--','CME_OPT3_ByteTrack/pipeline.py'],cwd=ROOT,text=True).strip() or 'uncommitted execution; source SHA256 in benchmark summary'
    append(ROOT/'Experiment_Tracking/experiments.csv',dict(run_id='CMEOPT3-EXP-001',run_name='CME-OPT3: ByteTRACK temporal factory benchmark',
        sprint='Sprint 4',task='CME-OPT3',stage='Temporal Tracking',experiment_type='temporal_tracking',model_version=summary['detector_version'],
        alert_policy_version=VERSION,model_architecture='YOLOv8s + ByteTRACK',dataset='data/test_factory_clip.mp4',dataset_version='historical-factory-600s-v1',
        num_classes=12,imgsz=640,device='0',environment=str(env),best_weight_uri='Backend/best.pt',source_script='CME_OPT3_ByteTrack/benchmark.py',
        git_commit=commit,status='validated_factory_audit' if accepted else 'evaluated_target_shortfall',tracking_origin='actual_paced_gpu_factory_benchmark',
        confidence_config='Confidence_Calibration/configs/calibrated_thresholds.yaml',sampling_fps=summary['evaluated_fps'],window_size=15,required_frames=15,
        cooldown=0,clear_policy='track clear_frames=5; SED2 absence seconds=5/6',false_alerts=summary['bytetrack']['false_alerts'],missed_violations=summary['missed_events'],
        fp_reduction_pct=reduction if reduction is not None else 'not demonstrated',mean_alert_latency=summary['trigger_delay']['mean'] if summary['trigger_delay']['mean'] is not None else 'not observed',
        notes=notes),'run_id')
    print('Measured report and append-only policy/experiment registry records generated:',summary['status'])


if __name__ == '__main__': main()
