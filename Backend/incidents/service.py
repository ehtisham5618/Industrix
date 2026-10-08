from __future__ import annotations
import logging
import math
import threading
import time
from pathlib import Path
from urllib.parse import urlparse
from functools import lru_cache
from ESE_CPU1_Quantization.common import NAMES,SOURCE_VERSION
from .repository import IncidentRepository,event_key,utc
from .snapshot import write_snapshot
from . import VERSION

LOG=logging.getLogger(__name__)

class IncidentLogger:
    def __init__(self,repository=None,is_sample=False):
        self.repository=repository or IncidentRepository();self.is_sample=is_sample
        self.lock=threading.RLock();self.failures=0;self.last_error=None

    def on_transition(self,event):
        try:self.repository.lifecycle(event)
        except Exception as exc:self.failed('INCIDENT_UPDATE_FAILED',exc,event.get('event_id'))

    def failed(self,action,exc,event_id):
        self.failures+=1;self.last_error=type(exc).__name__
        LOG.error('%s event_id=%s timestamp=%s error_type=%s',action,event_id,utc(),type(exc).__name__)

    def observe(self,packet,result,camera,engine='Unknown'):
        """Called after inference/tracker locks are released. Never export here."""
        for event in result.escalations:
            try:
                meta=event.get('metadata') or {};violation_id=meta.get('violation_id')
                if event.get('state') not in ('info','warning','critical'):continue
                if meta.get('source')!='cmeopt3_confirmed' or not violation_id:continue
                detection=next((d for d in result.detections if d.get('event_id')==violation_id and
                    d.get('confirmation_status') in ('confirmed','active') and d.get('confirmed_at') is not None),None)
                if detection is None:continue
                if detection.get('persist_frames_required',0)<15:continue
                class_id=int(detection['class_id'])
                if not 0<=class_id<len(NAMES) or detection['class_name']!=NAMES[class_id] or event['hazard_class']!=NAMES[class_id]:
                    raise ValueError('Incident class does not match the active model mapping')
                confidence=float(detection['confidence'])
                if not math.isfinite(confidence) or not 0<=confidence<=1:raise ValueError('Invalid confidence')
                bbox=detection['coordinates'];values=[float(bbox[k]) for k in ('x1','y1','x2','y2')]
                if not all(math.isfinite(v) for v in values) or values[2]<=values[0] or values[3]<=values[1]:raise ValueError('Invalid box')
                h,w=packet.frame.shape[:2]
                data=dict(source_event_key=event_key(event),event_id=event['event_id'],violation_id=violation_id,
                    timestamp=utc(event['first_seen']),camera_id=camera.camera_id,camera_location=camera.name,
                    class_id=class_id,class_name=NAMES[class_id],confidence=confidence,severity=event['severity'],
                    bbox_x1=values[0],bbox_y1=values[1],bbox_x2=values[2],bbox_y2=values[3],image_width=w,image_height=h,
                    track_id=detection.get('track_id'),geofence_id=detection.get('geofence_id'),
                    confirmation_frames=detection.get('persistence_frames'),first_seen=utc(detection['first_seen']),
                    confirmed_at=utc(detection['confirmed_at']),last_seen=utc(event['last_seen']),
                    engine_version=engine,detector_version=SOURCE_VERSION,alert_policy_version='cmeopt3-bytetrack15-v1',
                    is_sample=int(self.is_sample or (camera.loop and not urlparse(camera.source).scheme.lower() in ('http','https','rtsp','rtsps') and
                        Path(camera.source).suffix.lower() in ('.mp4','.webm','.avi','.mkv','.mov'))))
                with self.lock:
                    row,created=self.repository.reserve(data)
                    if created:LOG.info('INCIDENT_CREATED incident_id=%s event_id=%s timestamp=%s',row['incident_id'],event['event_id'],utc())
                    if created or self.repository.claim_snapshot(row['incident_id']):
                        try:
                            evidence=write_snapshot(self.repository.snapshots,row['incident_id'],camera.camera_id,NAMES[class_id],packet.frame,bbox)
                            evidence.update(evidence_frame_id=packet.frame_id,evidence_timestamp=utc(packet.timestamp))
                            self.repository.finish_snapshot(row['incident_id'],evidence)
                            LOG.info('SNAPSHOT_WRITTEN incident_id=%s event_id=%s timestamp=%s',row['incident_id'],event['event_id'],utc())
                        except Exception as exc:
                            self.repository.finish_snapshot(row['incident_id'],dict(snapshot_status='failed',snapshot_error=type(exc).__name__))
                            self.failed('SNAPSHOT_WRITE_FAILED',exc,event['event_id'])
                    self.repository.lifecycle(event)
            except Exception as exc:self.failed('INCIDENT_LOG_FAILED',exc,event.get('event_id'))

@lru_cache(maxsize=1)
def get_logger():return IncidentLogger()
