"""Deterministic detector-output replay through real ByteTRACK/SED-2/audit.

Image is from the existing local hazmat exercise clip. Boxes/confidence are
controlled test inputs; this is explicitly not an operational detection.
"""
import json
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import cv2
from Backend.incidents.repository import IncidentRepository,ROOT
from Backend.incidents.service import IncidentLogger
from CME_OPT3_ByteTrack.pipeline import TrackAwarePolicy
from Confidence_Calibration.scripts.alert_policy import load_policy_config
from SED_1_Multi_Camera.scripts.models import FramePacket
from SED_1_Multi_Camera.scripts.config import load_camera_configs
from SED_1_Multi_Camera.scripts.stream_manager import MultiCameraStreamManager
from SED_2_Alert_Escalation.scripts.factory import create_default_escalation_manager

def create_sample(directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    repo=IncidentRepository(directory/'events.db',directory/'snapshots')
    if repo.list():raise RuntimeError('Sample database already has incidents; use a new fixture directory')
    camera=load_camera_configs(ROOT/'SED_1_Multi_Camera/configs/3_cameras.json')[1]
    source=cv2.VideoCapture(camera.source);source.set(cv2.CAP_PROP_POS_MSEC,20000)
    ok,frame=source.read();source.release()
    if not ok:raise RuntimeError('Existing local hazmat fixture video unavailable')
    logger=IncidentLogger(repo,is_sample=True)
    sed=create_default_escalation_manager(ROOT);sed.event_store.transition_callback=logger.on_transition
    manager=MultiCameraStreamManager([camera],SimpleNamespace(),
        alert_policy_factory=lambda:TrackAwarePolicy(load_policy_config(ROOT/'Confidence_Calibration/configs/calibrated_thresholds.yaml')),
        escalation_manager=sed,result_callback=lambda packet,result:logger.observe(packet,result,camera,'Controlled detector-output replay; no model inference'))
    h,w=frame.shape[:2]
    # Explicitly controlled input ROI, not asserted as ground-truth chemical spill.
    det=dict(class_id=7,class_name='chemical hazard',confidence=.93,
        coordinates=dict(x1=.64*w,y1=.63*h,x2=.97*w,y2=.95*h))
    candidate_counts=[]
    for index in range(15):
        packet=FramePacket(camera.camera_id,index,time.time(),frame.copy(),30)
        manager._route_result(packet,[dict(det)],.001,.001)
        candidate_counts.append(len(repo.list()))
    assert candidate_counts[:14]==[0]*14 and candidate_counts[14]==1
    row=repo.list()[0]
    for index in range(15,20):
        manager._route_result(FramePacket(camera.camera_id,index,time.time(),frame.copy(),30),[dict(det)],.001,.001)
    assert len(repo.list())==1
    result=dict(incident=row,candidate_row_counts=candidate_counts,rows_after_repeated_active_frames=len(repo.list()),
        image_source=str(Path(camera.source).relative_to(ROOT)),source_frame_seek_ms=20000,
        fixture='Controlled detector-output replay through real ByteTRACK, strict15 confirmation, SED-2 and SQLite; image is from local training exercise',
        logger_failures=logger.failures)
    (directory/'sample_trace.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result

if __name__=='__main__':
    print(json.dumps(create_sample(ROOT/'IFE_UI2_Incident_Audit/runtime/demo_v2'),indent=2))
