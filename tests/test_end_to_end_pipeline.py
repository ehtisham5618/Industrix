"""Real local INT8 -> ByteTRACK -> SED-2 -> SQLite -> snapshot -> PDF/API.

Run with the backend interpreter. No mocked detector, tracker, rules or storage.
These fast tests route captured frames through the production result handler;
the separately recorded run verifies concurrent async capture and real browser.
"""
import asyncio
import io
import json
import socket
import time
import tempfile
from pathlib import Path

import cv2
import httpx
import pytest
from pypdf import PdfReader

from Backend.offline_policy import configure_local_runtime
configure_local_runtime()
from Backend.incidents.repository import IncidentRepository
from Backend.incidents.service import IncidentLogger
from Backend.incidents.pdf import export_pdf
from CME_OPT3_ByteTrack.pipeline import TrackAwarePolicy
from Confidence_Calibration.scripts.alert_policy import load_policy_config
from ESE_CPU1_Quantization.common import ROOT,NAMES,digest
from ESE_CPU3_Soak_Test.engine import OpenVINODetector
from SED_1_Multi_Camera.scripts.camera_source import FileCameraSource
from SED_1_Multi_Camera.scripts.config import load_camera_configs
from SED_1_Multi_Camera.scripts.models import FramePacket
from SED_1_Multi_Camera.scripts.stream_manager import MultiCameraStreamManager
from SED_2_Alert_Escalation.scripts.factory import create_default_escalation_manager

@pytest.fixture(scope='module')
def detector():
    # Any unexpected socket use fails immediately, including SDK emitters.
    from IFE_UI3_Demo_Packaging.offline_server import install_guard
    connect=socket.socket.connect;connect_ex=socket.socket.connect_ex
    install_guard()
    try:
        model=OpenVINODetector()
        yield model
        model.close()
    finally:socket.socket.connect=connect;socket.socket.connect_ex=connect_ex

def test_selected_model_cpu_and_exact_class_map(detector):
    assert detector.verification['execution_devices']==['CPU']
    assert len(detector.names)==12
    assert [detector.names[i] for i in range(12)]==NAMES
    assert any(p.lower() in ('i8','u8') for p in detector.verification['runtime_precision_counts'])

def test_non_loopback_tcp_is_blocked(detector):
    with socket.socket() as sock:
        with pytest.raises(OSError,match='Non-loopback'):sock.connect(('203.0.113.1',443))

def test_three_real_local_sources_and_output_contract(detector):
    cameras=load_camera_configs(ROOT/'SED_1_Multi_Camera/configs/3_cameras.json')
    assert len(cameras)==3 and len({c.camera_id for c in cameras})==3
    for camera in cameras:
        source=FileCameraSource(camera.source,loop=False,realtime=False)
        try:
            source.open();ok,frame=source.read();assert ok and frame.size
            output,_=detector.predict_batch([frame])
            for d in output[0]:
                assert 0<=d['class_id']<12 and d['class_name']==detector.names[d['class_id']]
                assert 0<=d['confidence']<=1
                x=d['coordinates'];h,w=frame.shape[:2]
                assert 0<=x['x1']<x['x2']<=w and 0<=x['y1']<x['y2']<=h
        finally:source.close()

@pytest.fixture
def incident_storage():
    base=ROOT/'IFE_UI3_Demo_Packaging/runtime';base.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='pytest_incident_',dir=base) as name:yield Path(name)

def test_real_hazard_confirmation_incident_pdf_restart_and_api(detector,incident_storage,monkeypatch):
    tmp_path=incident_storage
    repo=IncidentRepository(tmp_path/'events.db',tmp_path/'snapshots')
    logger=IncidentLogger(repo,is_sample=True)
    sed=create_default_escalation_manager(ROOT);sed.event_store.transition_callback=logger.on_transition
    camera=load_camera_configs(ROOT/'SED_1_Multi_Camera/configs/3_cameras.json')[1]
    manager=MultiCameraStreamManager([camera],detector,
        alert_policy_factory=lambda:TrackAwarePolicy(load_policy_config(ROOT/'Confidence_Calibration/configs/calibrated_thresholds.yaml')),
        escalation_manager=sed,result_callback=lambda packet,result:logger.observe(packet,result,camera,'OpenVINO INT8 (CPU)'))
    asset=ROOT/'tests/assets/ife_ui3_fire.png'
    provenance=json.loads((ROOT/'IFE_UI3_Demo_Packaging/reports/fixture_provenance.json').read_text(encoding='utf-8'))
    assert digest(asset)==provenance['fixture_sha256']
    image=cv2.imread(str(asset));assert image is not None
    start=time.time();counts=[];track_ids=[]
    for n in range(18):
        # Every evaluation runs actual model inference; no replayed boxes.
        ds,seconds=detector.predict_batch([image])
        assert any(d['class_name']=='fire' and d['confidence']>.25 for d in ds[0])
        packet=FramePacket(camera.camera_id,n*4,start+n,image.copy(),25)
        manager._route_result(packet,ds[0],seconds,seconds)
        counts.append(len(repo.list()))
        result=manager.latest_results[camera.camera_id]
        track_ids.append([d['track_id'] for d in result.detections if d['class_name']=='fire'])
    assert counts[:14]==[0]*14 and all(c==1 for c in counts[14:])
    assert all(ids and ids[0]==track_ids[0][0] for ids in track_ids)
    assert logger.failures==0
    row=repo.list()[0];assert row['class_name']=='fire' and row['severity']=='critical'
    assert row['is_sample'] and row['snapshot_status']=='ready'
    assert repo.snapshot_file(row).is_file()
    # Reopen persistent storage and fresh-export through the shared service.
    restored=IncidentRepository(repo.database,repo.snapshots,initialize=False)
    data,seconds=export_pdf(restored,row['incident_id']);assert seconds<2
    pdf=PdfReader(io.BytesIO(data));text='\n'.join(p.extract_text() for p in pdf.pages)
    assert len(pdf.pages)>=2 and sum(len(p.images) for p in pdf.pages)>0
    for value in (row['incident_id'],'CRITICAL','SAMPLE / DEMONSTRATION','Signature','Corrective'):assert value in text
    from Backend.main import api_app
    from Backend.incidents import api as incident_api
    monkeypatch.setattr(incident_api,'get_logger',lambda:logger)
    async def contract():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api_app),base_url='http://127.0.0.1') as client:
            response=await client.get('/incidents');assert response.status_code==200
            assert response.json()['incidents'][0]['incident_id']==row['incident_id']
            prefix='/incidents/'+row['incident_id']
            assert (await client.get(prefix+'/snapshot')).headers['content-type']=='image/jpeg'
            response=await client.post(prefix+'/export');assert response.status_code==200
            assert response.headers['content-type']=='application/pdf' and response.content.startswith(b'%PDF-')
            assert float(response.headers['x-pdf-generation-ms'])<2000
            assert (await client.get('/incidents/INC-2026-999999')).status_code==404
            status=(await client.get('/system/status')).json()
            assert len(status['model_classes'])==12 and status['capabilities']['forklift_proximity'] is False
    asyncio.run(contract())

def test_live_telemetry_reports_real_infer_request_timings(detector):
    from Backend.live_console import ConsoleTelemetry
    from types import SimpleNamespace
    metrics=ConsoleTelemetry().sample(SimpleNamespace(detector=detector,metrics={}))
    _,recent=detector.snapshot()
    assert metrics['model_inference_samples']==len(recent)>0
    assert metrics['model_inference_mean_ms']==pytest.approx(sum(r[0] for r in recent)/len(recent))
    assert metrics['model_inference_p95_ms']>=metrics['model_inference_mean_ms']
