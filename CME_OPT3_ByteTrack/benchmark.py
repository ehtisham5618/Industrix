"""Same-video, same-detector comparison with independently supplied event truth."""
import argparse
import csv
import hashlib
import json
import platform
from pathlib import Path
from time import perf_counter, sleep

import numpy as np
from Confidence_Calibration.scripts.alert_policy import AlertPolicy, load_policy_config
from SED_1_Multi_Camera.scripts.models import CameraConfig
from SED_1_Multi_Camera.scripts.detector import SharedYOLODetector
from SED_2_Alert_Escalation.scripts.factory import create_default_escalation_manager
from .pipeline import DEFAULT_TRACKER, TrackAwarePolicy


def digest(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def write_csv(path, rows, fields):
    with Path(path).open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def match_alerts(alerts, events):
    for alert in alerts:
        matches = [e['event_id'] for e in events if e['class_name'] == alert['class_name']
                   and float(e['start_seconds']) <= alert['timestamp_sec'] <= float(e['end_seconds'])]
        alert['matched_events'] = ';'.join(matches)
        alert['false_alert'] = not bool(matches)
    return {'formal_alerts': len(alerts), 'false_alerts': sum(a['false_alert'] for a in alerts),
            'true_alerts': sum(not a['false_alert'] for a in alerts)}


def latency_rows(events, alerts, mode, realtime=False):
    rows = []
    for event in events:
        candidates = [a for a in alerts if event['event_id'] in a['matched_events'].split(';')]
        first = min(candidates, key=lambda a:a['timestamp_sec']) if candidates else None
        confirmation = (first['confirmation_wall_seconds'] if realtime else first['timestamp_sec']) if first else None
        delay = confirmation-float(event['start_seconds']) if first else None
        rows.append({'mode': mode, 'event_id': event['event_id'], 'class_name': event['class_name'],
                     'start_seconds': float(event['start_seconds']), 'end_seconds': float(event['end_seconds']),
                     'confirmation_seconds': confirmation if first else '',
                     'confirmation_media_seconds': first['timestamp_sec'] if first else '',
                     'delay_seconds': delay if delay is not None else '', 'within_2s': delay is not None and delay <= 2,
                     'missed': first is None})
    return rows


def main():
    import cv2
    import torch
    import ultralytics
    parser = argparse.ArgumentParser()
    parser.add_argument('--video', required=True)
    parser.add_argument('--events', required=True)
    parser.add_argument('--weights', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--start', type=float, default=0)
    parser.add_argument('--duration', type=float, default=600)
    parser.add_argument('--evaluated-fps', type=float, default=10)
    parser.add_argument('--device', default='cpu')
    parser.add_argument('--tracker', default=str(DEFAULT_TRACKER))
    parser.add_argument('--persist-frames', type=int, default=15)
    parser.add_argument('--realtime', action='store_true', help='Pace frames to video time and measure actual wall-clock alert delay')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    with Path(args.events).open(encoding='utf-8', newline='') as f:
        events = list(csv.DictReader(f))
    if not events or any(e['verified'].lower() != 'true' for e in events):
        raise ValueError('A nonempty independently verified event annotation file is required')
    if args.evaluated_fps <= 0 or args.duration <= 0:
        raise ValueError('Positive duration and evaluated FPS required')
    capture = cv2.VideoCapture(args.video)
    if not capture.isOpened(): raise FileNotFoundError(args.video)
    fps = capture.get(cv2.CAP_PROP_FPS)
    full_duration = capture.get(cv2.CAP_PROP_FRAME_COUNT)/fps
    if full_duration + .1 < args.start+args.duration: raise ValueError('Requested segment exceeds video duration')
    config = load_policy_config(root / 'Confidence_Calibration/configs/calibrated_thresholds.yaml')
    baseline = AlertPolicy(config)
    tracked = TrackAwarePolicy(config, args.persist_frames, args.tracker)
    camera = CameraConfig('factory_01', 'Factory benchmark', args.video, loop=False)
    escalations = {name:create_default_escalation_manager(root) for name in ('baseline','bytetrack')}
    detector = SharedYOLODetector(args.weights, device=args.device)
    assert len(detector.model.names) == 12
    detector.model.predict(np.zeros((288,384,3),dtype=np.uint8), device=args.device, imgsz=640, conf=.1, verbose=False)
    alerts = {'baseline':[], 'bytetrack':[]}
    timings = dict(inference=0., baseline=0., bytetrack=0., decode=0.)
    evaluated = 0
    raw_frame = 0
    next_time = args.start
    first_media = last_media = None
    started = perf_counter()
    # Sequential decode preserves actual source PTS/cadence; no synthetic frames.
    try:
        with (output / 'frame_diagnostics.csv').open('w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f,fieldnames=['timestamp','raw_frame','detections','tracked_detections','candidate_states'])
            writer.writeheader()
            while True:
                decode_started = perf_counter()
                ok, frame = capture.read()
                timings['decode'] += perf_counter()-decode_started
                if not ok: break
                media = raw_frame/fps
                raw_frame += 1
                if media >= args.start+args.duration: break
                if media+1e-9 < next_time: continue
                next_time += 1/min(args.evaluated_fps, fps)
                timestamp = media-args.start
                if first_media is None:
                    started = perf_counter()
                if args.realtime:
                    sleep(max(0, timestamp-(perf_counter()-started)))
                first_media = timestamp if first_media is None else first_media
                last_media = timestamp
                infer_started = perf_counter()
                predictions = detector.model.predict(frame, conf=.1, imgsz=640, device=args.device, verbose=False)
                if torch.cuda.is_available(): torch.cuda.synchronize()
                timings['inference'] += perf_counter()-infer_started
                detections = detector._convert_result(predictions[0])
                t = perf_counter()
                old = baseline.process_frame(detections, evaluated, timestamp)
                old_confirmed = [d for d in old['calibrated_detections'] if baseline.manager.active[d['class_name']]]
                escalations['baseline'].process_frame(camera.camera_id, old_confirmed, timestamp)
                timings['baseline'] += perf_counter()-t
                t = perf_counter()
                new = tracked.process_camera(detections, camera, frame, evaluated, timestamp)
                escalations['bytetrack'].process_frame(camera.camera_id, new['confirmed_violations'], timestamp)
                timings['bytetrack'] += perf_counter()-t
                for name, result in [('baseline',old),('bytetrack',new)]:
                    for alert in result['alerts']:
                        alerts[name].append({**alert, 'timestamp_sec':timestamp, 'camera_id':camera.camera_id,
                            'confirmation_wall_seconds':perf_counter()-started})
                writer.writerow(dict(timestamp=timestamp,raw_frame=raw_frame,detections=len(detections),
                    tracked_detections=sum(d.get('track_id') is not None for d in new['detections']),
                    candidate_states=len(tracked.manager.states)))
                evaluated += 1
                if evaluated % 500 == 0: print(f'Processed {evaluated} frames; video time={timestamp:.3f}s',flush=True)
    finally:
        capture.release()
    elapsed = perf_counter()-started
    if evaluated == 0:
        raise RuntimeError('The video decoder produced zero evaluated frames; benchmark is invalid')
    totals = {name:match_alerts(rows, events) for name, rows in alerts.items()}
    latencies = [row for name,rows in alerts.items() for row in latency_rows(events,rows,name,args.realtime)]
    delays = [r['delay_seconds'] for r in latencies if r['mode']=='bytetrack' and not r['missed']]
    rows = [r for r in latencies if r['mode']=='bytetrack']
    reduction = (totals['baseline']['false_alerts']-totals['bytetrack']['false_alerts'])/totals['baseline']['false_alerts']*100 if totals['baseline']['false_alerts'] else None
    fields = ['camera_id','class_name','track_id','event_id','timestamp_sec','confirmation_wall_seconds','persistence_frames','matched_events','false_alert']
    for name,records in alerts.items(): write_csv(output/f'{name}_alerts.csv',records,fields)
    write_csv(output/'per_event_latency.csv',latencies,list(latencies[0]))
    processing = timings['inference']+timings['decode']
    sustainable = evaluated/(processing+timings['bytetrack'])
    media_fps = evaluated/args.duration
    onset_uncertainty = 1.0  # Independently reviewed source intervals; see annotations/README.md.
    status = bool(args.realtime and reduction is not None and reduction >= 40 and len(delays)==len(events)
                  and max(delays,default=999)+onset_uncertainty<=2 and sustainable >= media_fps)
    summary = dict(video_duration_seconds=args.duration, full_source_duration_seconds=full_duration,
        execution_sources_sha256={name:digest(root/name) for name in (
            'CME_OPT3_ByteTrack/pipeline.py','CME_OPT3_ByteTrack/benchmark.py','Backend/configs/bytetrack.yaml',
            'SED_1_Multi_Camera/scripts/models.py','SED_1_Multi_Camera/scripts/stream_manager.py',
            'SED_1_Multi_Camera/scripts/geofence.py','SED_1_Multi_Camera/scripts/detector.py',
            'Confidence_Calibration/scripts/alert_policy.py','Confidence_Calibration/configs/calibrated_thresholds.yaml',
            'SED_2_Alert_Escalation/scripts/escalation_state.py')},
        segment_start_seconds=args.start, source_fps=fps, evaluated_fps=media_fps, evaluated_frames=evaluated,
        actual_processing_fps=sustainable, persist_frames=args.persist_frames, theoretical_15_frame_seconds=15/media_fps,
        tracker='ByteTRACK',tracker_config=str(args.tracker), tracker_sha256=digest(args.tracker),
        detector_version='cme-opt2-focal-cosine-12class-v1', detector_sha256=digest(args.weights),names=detector.model.names,
        video_sha256=digest(args.video),annotation_sha256=digest(args.events),
        baseline=totals['baseline'],bytetrack=totals['bytetrack'], false_alert_reduction_pct=reduction,
        true_events=len(events),events_triggered=len(delays),events_within_2s=sum(r['within_2s'] for r in rows),
        missed_events=sum(r['missed'] for r in rows),trigger_delay={k:float(v) if delays else None for k,v in
            [('mean',np.mean(delays) if delays else 0),('p50',np.percentile(delays,50) if delays else 0),
             ('p95',np.percentile(delays,95) if delays else 0),('max',max(delays,default=0))]},
        annotation_onset_uncertainty_seconds=onset_uncertainty,
        events_within_2s_conservative=sum(not r['missed'] and r['delay_seconds']+onset_uncertainty<=2 for r in rows),
        tracking={**tracked.manager.stats,'live_states_at_video_end':len(tracked.manager.states),
                  'id_switches':None,'fragmentation':None},
        performance=dict(fps_before=evaluated/(processing+timings['baseline']),fps_after=sustainable,
            tracking_and_escalation_ms_per_frame=timings['bytetrack']/evaluated*1000,
            baseline_and_escalation_ms_per_frame=timings['baseline']/evaluated*1000,
            shared_inference_seconds=timings['inference'],decode_seconds=timings['decode'],actual_run_seconds=elapsed),
        environment=dict(python=platform.python_version(),ultralytics=ultralytics.__version__,torch=torch.__version__,
            cuda=torch.version.cuda,gpu=torch.cuda.get_device_name() if torch.cuda.is_available() else None),
        timing_basis='Paced source occurrence times and actual monotonic confirmation clock' if args.realtime else 'Offline media timestamps; cannot satisfy wall-clock latency acceptance',
        matching='Same class; alert confirmation point falls within verified event interval; zero temporal tolerance. Multiple independently confirmed tracks inside one scene event remain true alerts.',
        status='PASS' if status else 'FAIL')
    tracked.reset()
    summary['tracking']['live_states_after_cleanup'] = len(tracked.manager.states)
    for manager in escalations.values(): manager.reset_camera(camera.camera_id, args.duration)
    summary['sed2_active_events_after_cleanup'] = sum(len(m.active_events()) for m in escalations.values())
    (output/'benchmark_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2),flush=True)
    # Existing CME-3 helper, shared existing experiment, no new tracking framework.
    tracking_root = Path('/tracking/mlruns')
    if Path('/tracking').exists():
        from Experiment_Tracking.scripts.mlflow_utils import configure_tracking
        mlflow = configure_tracking(tracking_root)
        with mlflow.start_run(run_name='CME-OPT3: ByteTRACK factory benchmark') as run:
            mlflow.set_tags(dict(task='CME-OPT3',experiment_type='temporal_tracking',sprint='Sprint 4',status=summary['status']))
            mlflow.log_params(dict(detector_version=summary['detector_version'],detector_sha256=summary['detector_sha256'],
                tracker='ByteTRACK',persist_frames=15,lr_training='not applicable; no retraining',baseline='existing CME-2 calibrated 3-of-5',
                annotation_sha256=summary['annotation_sha256'],benchmark_video='Twentse_textielindustrie-948017.ogv'))
            metrics=dict(evaluated_fps=media_fps,baseline_false_alerts=totals['baseline']['false_alerts'],
                tracked_false_alerts=totals['bytetrack']['false_alerts'],events_within_2s=summary['events_within_2s'],missed_events=summary['missed_events'],
                fps_before=summary['performance']['fps_before'],fps_after=sustainable)
            if reduction is not None: metrics['false_alert_reduction_pct']=reduction
            if delays: metrics.update(mean_alert_delay=summary['trigger_delay']['mean'],max_alert_delay=max(delays))
            mlflow.log_metrics(metrics)
            mlflow.log_artifacts(str(output))
            summary['mlflow_run_id']=run.info.run_id
        (output/'benchmark_summary.json').write_text(json.dumps(summary,indent=2)+'\n')


if __name__ == '__main__': main()
