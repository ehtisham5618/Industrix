import asyncio
import json
import os
import struct
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch,Mock
import numpy as np
import httpx
import requests

from Backend.live_console import DisplayHub,ConsoleTelemetry,privacy_status
from Frontend.api_client import APIClient,engine_label,cloud_label,camera_label,telemetry_values
from SED_1_Multi_Camera.scripts.models import CameraConfig,FramePacket,DetectionResult,GeofenceConfig


class PresentationTests(unittest.TestCase):
    def test_url_rejects_credentials_and_non_http(self):
        for url in ('file:///private','http://user:secret@host','ftp://host','bad'):
            with self.assertRaises(ValueError):APIClient(url)
        self.assertEqual(APIClient('http://localhost:8000/').base_url,'http://localhost:8000')

    def test_engine_follows_actual_backend(self):
        self.assertEqual(engine_label(dict(active=True,name='OpenVINO',precision='INT8',device='cpu')),'OpenVINO INT8 (CPU)')
        self.assertEqual(engine_label(dict(active=True,name='PyTorch',precision='FP32',device='cuda:0')),'PyTorch FP32 (CUDA:0)')
        self.assertEqual(engine_label({}),'Idle')

    def test_privacy_never_falsely_zero(self):
        self.assertIn('0%',cloud_label(dict(local_processing_verified=True,cloud_dependency_percent=0)))
        for data in ({},dict(local_processing_verified=False,cloud_dependency_percent=0),dict(local_processing_verified=True,cloud_dependency_percent=None)):
            self.assertNotIn('0%',cloud_label(data))

    def test_camera_online_offline_reconnect(self):
        self.assertEqual(camera_label({'status':'running'}),'LIVE')
        self.assertEqual(camera_label({'status':'reconnecting'}),'RECONNECTING')
        for status in (None,{},dict(status='failed'),dict(status='stopped')):self.assertEqual(camera_label(status),'OFFLINE')

    def test_valid_and_missing_telemetry(self):
        self.assertEqual(telemetry_values(dict(telemetry=dict(cpu_system_percent=80,process_rss_mb=550,aggregate_evaluated_fps=3.3))),
                         dict(cpu_percent=80,rss_mib=550,evaluated_fps=3.3))
        self.assertTrue(all(v is None for v in telemetry_values({}).values()))
        self.assertIsNone(telemetry_values(dict(telemetry=dict(cpu_system_percent=float('nan'))))['cpu_percent'])

    def test_shutdown_retry_detail_reaches_operator(self):
        response=requests.Response();response.status_code=409
        response._content=b'{"detail":"Shutdown is still in progress. Retry Stop feeds."}'
        client=APIClient('http://localhost:8000')
        with patch.object(client.session,'request',return_value=response):
            with self.assertRaisesRegex(requests.HTTPError,'Retry Stop feeds'):client.request('POST','/streams/stop')


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.hub=DisplayHub();self.camera=CameraConfig('camera_01','Textile','file.mp4',monitored_classes={'stain'},
            geofences=[GeofenceConfig('zone',[(0,0),(1,0),(1,1)],{'stain'})])
        self.frame=np.zeros((720,1280,3),dtype=np.uint8)
        self.det=dict(class_id=6,class_name='stain',confidence=.8,coordinates=dict(x1=10,y1=20,x2=100,y2=200))

    def publish(self,n=4):
        tracked={**self.det,'track_id':17,'confirmation_status':'candidate','persistence_frames':3,'persist_frames_required':15}
        result=DetectionResult('camera_01',n,100,[tracked],raw_detections=[self.det],result_ready_at=101)
        self.hub.publish(FramePacket('camera_01',n,100,self.frame,25),result)

    def test_actual_coords_and_authoritative_tracker_survive_wire(self):
        self.publish();data,payload=self.hub.encode('camera_01',self.camera,{})
        count=struct.unpack('!I',data[:4])[0];wire=json.loads(data[4:4+count])
        self.assertEqual(data[4+count:4+count+2],b'\xff\xd8')
        self.assertEqual((wire['display_width'],wire['frame_width']),(960,1280))
        self.assertEqual(wire['detections'][0]['coordinates'],self.det['coordinates'])
        self.assertEqual(wire['detections'][0]['track_id'],17)
        self.assertEqual(wire['detections'][0]['persistence_frames'],3)
        self.assertEqual(wire['geofences'][0]['classes'],['stain'])

    def test_latest_only_and_reset_no_stale_frame(self):
        for n in range(80):self.publish(n)
        self.assertEqual(len(self.hub.latest),1)
        self.assertEqual(self.hub.encode('camera_01',self.camera,{})[1]['frame_id'],79)
        self.hub.reset();self.assertIsNone(self.hub.encode('camera_01',self.camera,{}));self.assertEqual(self.hub.generation,1)

    def test_missing_fields_and_untracked_detection(self):
        result=DetectionResult('camera_01',1,100,[],raw_detections=[self.det],result_ready_at=101)
        self.hub.publish(FramePacket('camera_01',1,100,self.frame,25),result)
        det=self.hub.encode('camera_01',self.camera,{})[1]['detections'][0]
        self.assertNotIn('track_id',det);self.assertEqual(det['confirmation_status'],'detected')

    def test_focus_does_not_invent_class(self):
        self.publish();camera=CameraConfig('camera_01','Chemical','file.mp4',monitored_classes={'chemical hazard'})
        self.assertEqual(self.hub.encode('camera_01',camera,{})[1]['detections'],[])

    def test_notification_and_unsubscribe(self):
        async def check():
            entry=self.hub.subscribe('camera_01');self.publish();await asyncio.wait_for(entry[1].wait(),1)
            self.hub.unsubscribe('camera_01',entry);self.assertEqual(self.hub.subscribers['camera_01'],[])
        asyncio.run(check())

    def test_external_mode_or_sources_no_false_privacy(self):
        with patch.dict(os.environ,{'DEPLOYMENT_MODE':'local','RUNTIME_EXTERNAL_SERVICES':''}):
            self.assertEqual(privacy_status([self.camera])['cloud_dependency_percent'],0)
            remote=CameraConfig('remote','Remote','rtsp://private-host/live')
            self.assertIsNone(privacy_status([remote])['cloud_dependency_percent'])
        with patch.dict(os.environ,{'DEPLOYMENT_MODE':'cloud','RUNTIME_EXTERNAL_SERVICES':''}):
            self.assertIsNone(privacy_status([self.camera])['cloud_dependency_percent'])
        with patch.dict(os.environ,{'DEPLOYMENT_MODE':'local','RUNTIME_EXTERNAL_SERVICES':'external inference'}):
            self.assertFalse(privacy_status([self.camera])['local_processing_verified'])

    def test_telemetry_comes_from_backend_monitor(self):
        telemetry=ConsoleTelemetry();sample=telemetry.sample(None)
        self.assertGreater(sample['process_rss_mb'],0)
        self.assertEqual(sample['aggregate_evaluated_fps'],0)
        self.assertEqual(sample['memory_units'],'MiB; process RSS')
        self.assertFalse(telemetry.monitor.enable_gpu)


class BackendInterfaceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import Backend.main as main
        self.main=main
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=main.api_app),base_url='http://test')
    async def asyncTearDown(self):await self.client.aclose()

    async def test_idle_status_actual_class_map_and_capability(self):
        data=(await self.client.get('/system/status')).json()
        self.assertFalse(data['engine']['active']);self.assertEqual(len(data['model_classes']),12)
        self.assertIn('chemical hazard',data['model_classes']);self.assertFalse(data['capabilities']['forklift_proximity'])

    async def test_stopped_manager_does_not_advertise_active_engine(self):
        manager=SimpleNamespace(scheduler_thread=threading.Thread(),metrics={},detector=SimpleNamespace(verification={'openvino_version':'test'}))
        with patch.object(self.main,'STREAM_MANAGER',manager):
            data=(await self.client.get('/system/status')).json()
            self.assertFalse(data['engine']['active']);self.assertEqual(data['engine']['name'],'Idle')

    async def test_three_configured_camera_roles(self):
        data=(await self.client.get('/cameras')).json()['cameras']
        self.assertEqual([c['name'] for c in data],['Textile Weaving Inspection','Chemical Storage Bay','Loading Dock'])
        self.assertEqual(data[2]['monitored_classes'],['no helmet'])
        self.assertTrue(all(c['simulation'] for c in data))

    async def test_engine_selection_validation(self):
        self.assertEqual((await self.client.post('/streams/start?engine=pretend')).status_code,422)
        self.assertEqual((await self.client.post('/streams/start?engine=openvino&device=cuda')).status_code,400)

    async def test_unavailable_stream_endpoints_graceful(self):
        self.assertEqual((await self.client.get('/cameras/camera_01/latest')).status_code,404)
        self.assertEqual((await self.client.get('/alerts/active')).status_code,404)

    async def test_incomplete_stop_keeps_existing_manager_and_returns_retry(self):
        manager=Mock();manager.stop.side_effect=RuntimeError('Inference still finishing')
        with patch.object(self.main,'STREAM_MANAGER',manager):
            response=await self.client.post('/streams/stop')
            self.assertEqual(response.status_code,409)
            self.assertIn('Retry Stop',response.json()['detail'])
            self.assertIs(self.main.STREAM_MANAGER,manager)

    async def test_start_during_incomplete_shutdown_does_not_create_another_session(self):
        manager=Mock();manager.stop.side_effect=RuntimeError('Capture still finishing')
        with patch.object(self.main,'STREAM_MANAGER',manager):
            response=await self.client.post('/streams/start?engine=openvino')
            self.assertEqual(response.status_code,409)
            self.assertIn('second session was not started',response.json()['detail'])
            self.assertIs(self.main.STREAM_MANAGER,manager)

    async def test_concurrent_stream_control_rejected_without_duplicate_manager(self):
        self.main.STREAM_CONTROL_LOCK.acquire()
        try:
            self.assertEqual((await self.client.post('/streams/start?engine=openvino')).status_code,409)
            self.assertEqual((await self.client.post('/streams/stop')).status_code,409)
            self.assertIsNone(self.main.STREAM_MANAGER)
        finally:self.main.STREAM_CONTROL_LOCK.release()

if __name__=='__main__':unittest.main()
