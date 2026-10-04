"""Calibrated ByteTRACK association and strict, camera-scoped confirmation."""
from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from Confidence_Calibration.scripts.alert_policy import ConfidenceCalibrator
from SED_1_Multi_Camera.scripts.geofence import filter_detections_for_camera

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRACKER = ROOT / 'Backend/configs/bytetrack.yaml'
DEFAULT_PERSIST_FRAMES = 15
POLICY_VERSION = 'cmeopt3-bytetrack15-v1'
_TRACKER_LOCK = threading.RLock()
logger = logging.getLogger(__name__)


def resolve_tracker(path):
    path = DEFAULT_TRACKER if str(path) == 'bytetrack.yaml' else Path(path)
    if not path.is_file():
        raise FileNotFoundError(f'Tracker configuration not found: {path}')
    return path


class CameraByteTracker:
    """One upstream tracker per semantic class, with no cross-camera association.

    Uses the documented BYTETracker.update API to retain shared batched YOLO
    inference and filter confidence before association. No tracker is vendored.
    """

    def __init__(self, config=DEFAULT_TRACKER):
        import yaml
        # Load optional native dependencies before live capture begins.
        from ultralytics.trackers.byte_tracker import BYTETracker  # noqa: F401
        self.config_path = resolve_tracker(config)
        self.args = SimpleNamespace(**yaml.safe_load(self.config_path.read_text()))
        if self.args.tracker_type != 'bytetrack':
            raise ValueError('CME-OPT3 requires tracker_type=bytetrack')
        self.trackers = {}
        self.calls = 0

    def update(self, detections, frame=None):
        import numpy as np
        from ultralytics.engine.results import Boxes
        from ultralytics.trackers.basetrack import BaseTrack
        from ultralytics.trackers.byte_tracker import BYTETracker
        by_class = {}
        for detection in detections:
            by_class.setdefault(int(detection['class_id']), []).append(detection)
        outputs = []
        # Upstream tracker initialization resets a process-global ID allocator.
        # Preserve it under a lock so adding/resetting a camera cannot reuse IDs.
        with _TRACKER_LOCK:
            for class_id in sorted(set(by_class) | set(self.trackers)):
                if class_id not in self.trackers:
                    count = BaseTrack._count
                    self.trackers[class_id] = BYTETracker(self.args, frame_rate=30)
                    BaseTrack._count = count
                source = by_class.get(class_id, [])
                rows = [[*[d['coordinates'][k] for k in ('x1', 'y1', 'x2', 'y2')],
                         d['confidence'], class_id] for d in source]
                boxes = Boxes(np.asarray(rows, dtype=np.float32).reshape(-1, 6), (1, 1))
                tracks = self.trackers[class_id].update(boxes, img=frame)
                assigned = set()
                for row in tracks:
                    index = int(row[-1])
                    assigned.add(index)
                    outputs.append({**source[index], 'track_id': int(row[4])})
                for index, detection in enumerate(source):
                    if index not in assigned:
                        outputs.append({**detection, 'track_id': None})
        self.calls += 1
        return outputs

    def reset(self):
        self.trackers.clear()
        self.calls = 0


@dataclass
class TrackState:
    camera_id: str
    track_id: int
    class_id: int
    class_name: str
    geofence_id: str | None
    first_seen: float
    last_seen: float
    consecutive_evaluated_frames: int = 0
    total_seen_frames: int = 0
    missed_frames: int = 0
    status: str = 'candidate'
    confirmed_at: float | None = None
    event_id: str | None = None


class TrackConfirmation:
    def __init__(self, config, persist_frames=DEFAULT_PERSIST_FRAMES):
        if persist_frames < 1:
            raise ValueError('persist_frames must be positive')
        self.config = config
        self.persist_frames = persist_frames
        self.states = {}
        self.last_frame = {}
        self.stats = dict(tracks_created=0, tracks_confirmed=0, candidate_tracks_expired=0,
                          tracks_cleared=0, max_live_states=0)

    def update(self, camera_id, detections, frame_index, timestamp):
        last = self.last_frame.get(camera_id)
        if last is not None and frame_index <= last:
            raise ValueError('Evaluated frames must increase; reset the stream before replaying')
        self.last_frame[camera_id] = frame_index
        seen, alerts, confirmed = set(), [], []
        for detection in detections:
            detection.update(camera_id=camera_id, frame_id=frame_index, timestamp=timestamp,
                             persist_frames_required=self.persist_frames)
            track_id = detection.get('track_id')
            name = detection['class_name']
            if track_id is None or name not in self.config.alert_classes:
                detection.update(confirmation_status='untracked' if track_id is None else 'tracked', persistence_frames=0)
                continue
            key = (camera_id, track_id, detection['class_id'], detection.get('geofence_id'))
            if key in seen:
                continue  # Duplicate boxes cannot advance a frame twice.
            seen.add(key)
            state = self.states.get(key)
            if state is None:
                state = self.states[key] = TrackState(camera_id, track_id, detection['class_id'], name,
                    detection.get('geofence_id'), timestamp, timestamp)
                self.stats['tracks_created'] += 1
                logger.debug('CANDIDATE_CREATED camera=%s track=%s class=%s timestamp=%s', camera_id, track_id, name, timestamp)
            if state.missed_frames and state.confirmed_at is None:
                state.first_seen = timestamp
            state.last_seen = timestamp
            state.missed_frames = 0
            state.consecutive_evaluated_frames += 1
            state.total_seen_frames += 1
            if state.confirmed_at is None and state.consecutive_evaluated_frames >= self.persist_frames:
                state.confirmed_at = timestamp
                state.status = 'confirmed'
                state.event_id = f'CMEOPT3-{uuid.uuid4().hex}'
                self.stats['tracks_confirmed'] += 1
                alert = {**detection, 'state': 'confirmed', 'event_id': state.event_id,
                         'timestamp_sec': timestamp, 'first_seen': state.first_seen,
                         'confirmed_at': timestamp, 'persistence_frames': state.consecutive_evaluated_frames}
                alerts.append(alert)
                logger.info('CONFIRMED camera=%s track=%s class=%s frames=%s timestamp=%s event=%s',
                    camera_id, track_id, name, state.consecutive_evaluated_frames, timestamp, state.event_id)
            elif state.confirmed_at is not None:
                state.status = 'active'
            detection.update(confirmation_status=state.status, persistence_frames=state.consecutive_evaluated_frames,
                             event_id=state.event_id, first_seen=state.first_seen, confirmed_at=state.confirmed_at)
            logger.debug('%s camera=%s track=%s class=%s frames=%s confidence=%s timestamp=%s event=%s',
                'ACTIVE' if state.confirmed_at else 'CANDIDATE_UPDATED', camera_id, track_id, name,
                state.consecutive_evaluated_frames, detection['confidence'], timestamp, state.event_id)
            if state.confirmed_at is not None:
                confirmed.append({**detection, 'source': 'cmeopt3_confirmed', 'violation_id': state.event_id})
        for key, state in list(self.states.items()):
            if key[0] != camera_id or key in seen:
                continue
            state.missed_frames += 1
            state.consecutive_evaluated_frames = 0  # Lost predictions never count as observed positives.
            limit = self.config.for_class(state.class_name).clear_frames
            if state.missed_frames >= max(1, limit):
                counter = 'tracks_cleared' if state.confirmed_at is not None else 'candidate_tracks_expired'
                self.stats[counter] += 1
                logger.debug('%s camera=%s track=%s class=%s timestamp=%s event=%s',
                    'CLEARED' if state.confirmed_at else 'EXPIRED', camera_id, state.track_id,
                    state.class_name, timestamp, state.event_id)
                del self.states[key]
        self.stats['max_live_states'] = max(self.stats['max_live_states'], len(self.states))
        return {'calibrated_detections': detections, 'alerts': alerts, 'confirmed_violations': confirmed}

    def reset(self):
        self.states.clear()
        self.last_frame.clear()


class TrackAwarePolicy:
    def __init__(self, config, persist_frames=DEFAULT_PERSIST_FRAMES, tracker=DEFAULT_TRACKER):
        self.calibrator = ConfidenceCalibrator(config)
        self.tracker = CameraByteTracker(tracker)
        self.manager = TrackConfirmation(config, persist_frames)
        self.session_id = None
        self.camera_id = None

    def process_camera(self, detections, camera, frame, frame_index, timestamp_sec, session_id=0):
        if self.camera_id is not None and camera.camera_id != self.camera_id:
            raise ValueError('A tracking policy instance belongs to exactly one camera')
        if self.session_id is not None and session_id != self.session_id:
            self.reset()
        self.session_id, self.camera_id = session_id, camera.camera_id
        calibrated = self.calibrator.filter(detections)
        tracked = self.tracker.update(calibrated, frame)
        relevant, matches = filter_detections_for_camera(tracked, camera, frame)
        output = self.manager.update(camera.camera_id, relevant, frame_index, timestamp_sec)
        def key(d):
            return (d['class_id'], d['track_id'], tuple(d['coordinates'][k] for k in ('x1','y1','x2','y2')))
        displayed = {key(d):d for d in relevant}
        tracked = [displayed.get(key(d), {**d, 'camera_id':camera.camera_id, 'frame_id':frame_index,
            'timestamp':timestamp_sec, 'confirmation_status':'outside_geofence', 'persistence_frames':0,
            'persist_frames_required':self.manager.persist_frames}) for d in tracked]
        output.update(detections=tracked, geofence_matches=matches)
        return output

    def reset(self):
        self.tracker.reset()
        self.manager.reset()
        self.session_id = None
        self.camera_id = None
