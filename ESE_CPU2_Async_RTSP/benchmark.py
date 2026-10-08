"""Run the existing shared detector/tracker/escalation pipeline on three paced feeds."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import statistics
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / 'SED_1_Multi_Camera/reports/ESE_CPU2'
CONFIG = ROOT / 'SED_1_Multi_Camera/configs/3_cameras.json'
VERSION = 'ESECPU2-async-ring15-sample4-v1'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2), encoding='utf-8')


def run(config=CONFIG, duration=180, phase='optimized'):
    if duration<=0:
        raise ValueError('test-duration must be positive')
    if phase=='baseline':
        # Prevent accidentally overwriting baseline evidence with the new manager.
        base='f239c770dfdaea862b4e108f3dacd3abc8c72484'
        for name in ('stream_manager.py','camera_source.py','models.py','config.py'):
            path='SED_1_Multi_Camera/scripts/'+name
            original=subprocess.check_output(['git','show',base+':'+path],cwd=ROOT)
            current=(ROOT/path).read_bytes()
            if original.replace(b'\r\n',b'\n')!=current.replace(b'\r\n',b'\n'):
                raise RuntimeError('Baseline requires the unchanged pre-CPU2 checkout '+base)
    import cv2
    import psutil
    import torch
    import ultralytics
    from dataclasses import asdict
    from SED_1_Multi_Camera.scripts.camera_source import FileCameraSource
    from SED_1_Multi_Camera.scripts.config import load_camera_configs
    from SED_1_Multi_Camera.scripts.detector import SharedYOLODetector
    from SED_1_Multi_Camera.scripts.stream_manager import MultiCameraStreamManager
    from SED_3_Stress_Testing.scripts.resource_monitor import ResourceMonitor
    from CME_OPT3_ByteTrack.pipeline import TrackAwarePolicy
    from Confidence_Calibration.scripts.alert_policy import load_policy_config
    from SED_2_Alert_Escalation.scripts.factory import create_default_escalation_manager

    REPORTS.mkdir(parents=True, exist_ok=True)
    # Ultralytics select_device resets this to NUM_THREADS on first prediction.
    from ultralytics.utils import NUM_THREADS
    torch.set_num_threads(NUM_THREADS)
    cv2.setNumThreads(1)
    cameras = load_camera_configs(config)
    if len(cameras) != 3:
        raise ValueError('Official benchmark requires exactly three enabled cameras')
    media = {}
    for camera in cameras:
        capture = cv2.VideoCapture(camera.source)
        if not capture.isOpened():
            raise RuntimeError(f'Configured local simulation is unavailable for {camera.camera_id}')
        media[camera.camera_id] = dict(path=Path(camera.source).relative_to(ROOT).as_posix(),
            sha256=digest(camera.source), encoded_fps=capture.get(cv2.CAP_PROP_FPS),
            width=capture.get(3), height=capture.get(4), frame_count=capture.get(7))
        capture.release()
    detector = SharedYOLODetector(ROOT / 'Backend/best.pt', device='cpu', imgsz=640)
    warmup = cv2.VideoCapture(cameras[0].source)
    ok, frame = warmup.read()
    warmup.release()
    if not ok:
        raise RuntimeError('Warmup input unavailable')
    for _ in range(3):
        detector.predict_batch([frame, frame, frame])
    policies = load_policy_config(ROOT / 'Confidence_Calibration/configs/calibrated_thresholds.yaml')
    manager = MultiCameraStreamManager(cameras, detector,
        alert_policy_factory=lambda: TrackAwarePolicy(policies),
        escalation_manager=create_default_escalation_manager(ROOT), micro_batch=True)

    # Identical wall-paced raw decoding for the original and refactored managers.
    # Original FileCameraSource decoded files as fast as possible, unlike live feeds.
    class PacedSource(FileCameraSource):
        def open(self):
            super().open()
            self.due = time.perf_counter()

        def read(self):
            manager.stop_event.wait(max(0, self.due - time.perf_counter()))
            if manager.stop_event.is_set():
                return False, None
            result = super().read()
            self.due += 1 / self.source_fps
            return result

    if phase == 'baseline':
        manager.source_factory = lambda cfg: PacedSource(cfg.source, cfg.loop)
    monitor = ResourceMonitor(interval_seconds=1, enable_gpu=False)
    started_at = datetime.now(timezone.utc).isoformat()
    monitor.start()
    started = time.perf_counter()
    manager.start()
    occupancy = []
    try:
        while time.perf_counter() - started < duration:
            manager.stop_event.wait(min(1, max(0, duration - (time.perf_counter() - started))))
            occupancy.append(dict(elapsed_seconds=time.perf_counter() - started,
                **{c: q.qsize() for c, q in manager.queues.items()}))
            if getattr(manager, 'scheduler_error', None):
                raise RuntimeError(manager.scheduler_error)
        capture_duration = time.perf_counter() - started
        evaluated_at_deadline = {c:m.processed for c,m in manager.metrics.items()}
    finally:
        manager.stop(timeout=30)
        monitor.stop()
    total_duration = time.perf_counter() - started
    # Exclude priming snapshot and shutdown/drain from the sustained CPU window.
    samples = [s.to_dict() for s in monitor.samples if 0.5 <= s.elapsed_seconds <= capture_duration]
    if not samples or monitor.exceptions:
        raise RuntimeError(f'Resource evidence unavailable: {monitor.exceptions}')
    logical = psutil.cpu_count()
    for sample in samples:
        sample['normalized_process_cpu_percent'] = sample['process_cpu_percent'] / logical
    streams = {}
    for camera in cameras:
        m = manager.metrics[camera.camera_id]
        values = asdict(m)
        for key in ('queue_depth_samples', 'inference_times', 'processing_times', 'latencies',
                    'frame_ages_ms', 'capture_sample_ms', 'sample_inference_ms'):
            sequence = list(values.pop(key, []))
            if sequence:
                values[key + '_mean'] = statistics.fmean(sequence)
                values[key + '_max'] = max(sequence)
        ring = manager.queues[camera.camera_id]
        if hasattr(ring, 'snapshot'):
            values['buffer'] = ring.snapshot()
        else:
            values['buffer'] = dict(capacity=ring.maxsize, true_overruns=m.overload_drops,
                                    final_occupancy=ring.qsize())
        fps = evaluated_at_deadline[camera.camera_id] / capture_duration
        streams[camera.camera_id] = dict(name=camera.name, source=media[camera.camera_id],
            captured=m.captured, selected_for_evaluation=m.eligible, evaluated=m.processed,
            evaluated_during_capture=evaluated_at_deadline[camera.camera_id],
            evaluated_during_drain=m.processed-evaluated_at_deadline[camera.camera_id],
            intentional_skips=m.configured_skips, source_fps=m.captured / capture_duration,
            evaluated_fps=fps, expected_15_observation_seconds=15 / fps if fps else None,
            counters=values)
    captured = sum(m.captured for m in manager.metrics.values())
    evaluated = sum(m.processed for m in manager.metrics.values())
    drops = sum(m.overload_drops + getattr(m, 'inference_drops', 0) for m in manager.metrics.values())
    cpu = dict(system_mean=statistics.fmean(s['cpu_percent'] for s in samples),
        system_peak=max(s['cpu_percent'] for s in samples),
        normalized_process_mean=statistics.fmean(s['normalized_process_cpu_percent'] for s in samples),
        normalized_process_peak=max(s['normalized_process_cpu_percent'] for s in samples),
        process_raw_mean=statistics.fmean(s['process_cpu_percent'] for s in samples), samples=len(samples))
    result = dict(phase=phase, config_version=VERSION, started_at_utc=started_at,
        requested_duration_seconds=duration, capture_duration_seconds=capture_duration,
        total_with_drain_seconds=total_duration, streams=streams, cpu=cpu,
        captured=captured, evaluated=evaluated, compute_frame_reduction_pct=100*(1-evaluated/captured),
        aggregate_evaluated_fps=sum(evaluated_at_deadline.values())/capture_duration, unintentional_drop_count=drops,
        buffer_overrun_count=sum(s['counters']['buffer']['true_overruns'] for s in streams.values()),
        network_rtp_packet_loss='not directly observable through OpenCV',
        actual_rtsp_protocol_test='NOT RUN; local video simulation',
        environment=dict(platform=platform.platform(), cpu=platform.processor(), logical_cpus=logical,
            physical_cpus=psutil.cpu_count(logical=False), ram_bytes=psutil.virtual_memory().total,
            torch=torch.__version__, ultralytics=ultralytics.__version__, opencv=cv2.__version__,
            precision='PyTorch FP32', model='Backend/best.pt', model_sha256=digest(ROOT/'Backend/best.pt'),
            imgsz=640, torch_threads=torch.get_num_threads(), cv_threads=cv2.getNumThreads(), micro_batch=True),
        manager_source_sha256=digest(ROOT/'SED_1_Multi_Camera/scripts/stream_manager.py'),
        git_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        live_threads_after_stop=[w.thread.name for w in manager.workers if w.thread.is_alive()],
        scheduler_alive_after_stop=manager.scheduler_thread.is_alive(),
        scheduler_error=getattr(manager,'scheduler_error',None),
        formal_alerts=len(manager.active_alerts), escalation_events=len(manager.escalation_manager.all_events()))
    result['status'] = 'PASS' if (duration >= 180 and drops == 0 and
        cpu['system_mean'] < 40 and cpu['normalized_process_mean'] < 40 and
        all(abs(s['evaluated_fps']-s['source']['encoded_fps']/4) < 0.5 for s in streams.values())) else 'FAIL'
    write_json(REPORTS / f'{phase}_metrics.json', result)
    for name, rows in [('cpu_timeseries', samples), ('buffer_occupancy', occupancy)]:
        with (REPORTS/f'{phase}_{name}.csv').open('w',newline='',encoding='utf-8') as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    print(json.dumps({k:result[k] for k in ('phase','capture_duration_seconds','cpu','captured',
        'evaluated','unintentional_drop_count','buffer_overrun_count','status')},indent=2),flush=True)
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',type=Path,default=CONFIG)
    parser.add_argument('--test-duration',type=float,default=180)
    parser.add_argument('--phase',choices=['baseline','optimized','smoke'],default='optimized')
    args=parser.parse_args()
    result=run(args.config,args.test_duration,args.phase)
    return 2 if args.phase=='optimized' and args.test_duration>=180 and result['status']=='FAIL' else 0


if __name__=='__main__':
    raise SystemExit(main())
