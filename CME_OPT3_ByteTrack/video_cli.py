"""Video entry point for Backend/main.py using the production tracking policy."""
import json
import logging
from pathlib import Path
from time import perf_counter

from Confidence_Calibration.scripts.alert_policy import load_policy_config
from SED_1_Multi_Camera.scripts.detector import SharedYOLODetector
from SED_1_Multi_Camera.scripts.models import CameraConfig
from SED_2_Alert_Escalation.scripts.factory import create_default_escalation_manager
from .pipeline import TrackAwarePolicy


def run_video(args, root):
    import cv2
    if args.evaluated_fps <= 0:
        raise ValueError('evaluated-fps must be positive')
    logging.basicConfig(level=logging.DEBUG if args.debug_tracker else logging.INFO)
    capture = cv2.VideoCapture(str(args.source))
    if not capture.isOpened():
        raise FileNotFoundError(f'Cannot open video: {args.source}')
    fps = capture.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        capture.release()
        raise ValueError('Video must provide a positive source FPS')
    detector = SharedYOLODetector(root / 'Backend/best.pt', device=args.device)
    policy = TrackAwarePolicy(load_policy_config(root / 'Confidence_Calibration/configs/calibrated_thresholds.yaml'),
                              args.persist_frames, args.tracker)
    escalation = create_default_escalation_manager(root, log_path=None)
    camera = CameraConfig('video_01', 'Video', str(args.source), loop=False)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    frame_id = evaluated = 0
    next_time = 0.0
    started = perf_counter()
    try:
        with output.open('w', encoding='utf-8') as stream:
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                timestamp = frame_id / fps
                frame_id += 1
                if timestamp + 1e-9 < next_time:
                    continue
                next_time += 1 / min(fps, args.evaluated_fps)
                results = detector.model.predict(frame, conf=args.conf, imgsz=640,
                    device=args.device, verbose=False)
                detections = detector._convert_result(results[0])
                evaluated += 1
                result = policy.process_camera(detections, camera, frame, frame_id, timestamp)
                result['escalations'] = [e.to_dict() for e in escalation.process_frame(camera.camera_id,
                    result['confirmed_violations'], timestamp)]
                stream.write(json.dumps({'frame_id': frame_id, 'timestamp': timestamp, **result}) + '\n')
    finally:
        capture.release()
        policy.reset()
        escalation.reset_camera(camera.camera_id)
    elapsed = perf_counter() - started
    print(json.dumps({'source_fps': fps, 'evaluated_frames': evaluated, 'video_duration_seconds': frame_id/fps,
        'evaluated_media_fps': evaluated/max(frame_id/fps, 1e-9), 'processing_fps': evaluated/elapsed,
        'persist_frames': args.persist_frames, 'output': str(output)}, indent=2))
