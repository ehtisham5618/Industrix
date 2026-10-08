import asyncio
import concurrent.futures
from contextlib import closing
import hashlib
import io
import json
import socket
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import cv2
import httpx
import numpy as np
from PIL import Image
from pypdf import PdfReader
from Backend.incidents.repository import IncidentRepository,event_key,utc
from Backend.incidents.service import IncidentLogger
from Backend.incidents.snapshot import crop_bounds
from Backend.incidents.pdf import export_pdf
from SED_1_Multi_Camera.scripts.models import CameraConfig,FramePacket,DetectionResult

class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.repo=IncidentRepository(self.root/'events.db',self.root/'snapshots');self.logger=IncidentLogger(self.repo,True)
        self.camera=CameraConfig('camera_02','Chemical Storage Bay','fixture')
        self.frame=np.full((360,640,3),170,dtype=np.uint8);self.now=time.time()
        self.det=dict(class_id=7,class_name='chemical hazard',confidence=.93,coordinates=dict(x1=100,y1=80,x2=220,y2=200),
            track_id=17,event_id='CMEOPT3-fixture',confirmed_at=self.now,first_seen=self.now-1,confirmation_status='confirmed',
            persistence_frames=15,persist_frames_required=15)
        self.event=dict(event_id='SED2-000001',camera_id='camera_02',hazard_class='chemical hazard',severity='warning',state='warning',
            first_seen=self.now,last_seen=self.now,duration=0,metadata=dict(violation_id='CMEOPT3-fixture',source='cmeopt3_confirmed'))
        self.packet=FramePacket('camera_02',14,self.now,self.frame,30)
        self.result=DetectionResult('camera_02',14,self.now,[self.det],escalations=[self.event])

    def record(self):
        self.logger.observe(self.packet,self.result,self.camera,'Controlled test replay');return self.repo.list()[0]

    def test_schema_wal_required_fields(self):
        with self.repo.connect() as db:
            self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0],'wal')
            fields={r[1] for r in db.execute('PRAGMA table_info(incidents)')}
        self.assertTrue({'incident_id','event_id','timestamp','camera_location','confidence','snapshot_path','bbox_x1','severity'}<=fields)

    def test_network_storage_rejected_and_privacy_claim_suppressed(self):
        from Backend.incidents.repository import local_storage_path
        from Backend.live_console import privacy_status
        self.assertFalse(local_storage_path(r'\\server\share\events.db'))
        self.assertFalse(local_storage_path('https://server/events.db'))
        with patch.dict('os.environ',{'INCIDENT_DATABASE':r'\\server\share\events.db','DEPLOYMENT_MODE':'local','RUNTIME_EXTERNAL_SERVICES':''}):
            self.assertIsNone(privacy_status([self.camera])['cloud_dependency_percent'])

    def test_confirmed_creates_one_row_and_valid_native_crop(self):
        row=self.record();self.assertEqual(row['incident_id'][:9],'INC-2026-')
        self.assertEqual(row['severity'],'warning');self.assertEqual(row['confidence'],.93)
        with Image.open(self.repo.snapshot_file(row)) as image:self.assertEqual(image.size,(144,144))

    def test_candidate_and_short_confirmation_produce_zero_rows(self):
        for status in ('candidate','untracked','tracked'):
            self.det['confirmation_status']=status;self.logger.observe(self.packet,self.result,self.camera)
        self.det['confirmation_status']='confirmed';self.det['persist_frames_required']=14
        self.logger.observe(self.packet,self.result,self.camera)
        self.assertEqual(self.repo.list(),[])

    def test_same_event_exactly_once_no_snapshot_rewrite(self):
        row=self.record();path=self.repo.snapshot_file(row);mtime=path.stat().st_mtime_ns
        for _ in range(5):self.record()
        self.assertEqual(len(self.repo.list()),1);self.assertEqual(path.stat().st_mtime_ns,mtime)

    def test_reopen_preserves_incident_and_sequence(self):
        row=self.record();repo=IncidentRepository(self.repo.database,self.repo.snapshots)
        self.assertEqual(repo.get(row['incident_id'])['snapshot_sha256'],row['snapshot_sha256'])
        self.event['metadata']['violation_id']='new-uuid';self.det['event_id']='new-uuid'
        self.record();self.assertEqual(len(repo.list()),2)

    def test_restart_sed_counter_cannot_collide(self):
        self.record();self.event['metadata']['violation_id']='another-cme-uuid';self.det['event_id']='another-cme-uuid'
        self.record();self.assertEqual(len(self.repo.list()),2)

    def test_resolved_event_and_new_episode(self):
        row=self.record();self.event['state']='resolved';self.event['metadata']['resolution_observed_at']=self.now+8
        self.logger.on_transition(self.event);self.assertEqual(self.repo.get(row['incident_id'])['status'],'RESOLVED')
        self.event.update(state='warning',first_seen=self.now+9,last_seen=self.now+9)
        self.record();self.assertEqual(len(self.repo.list()),2)

    def test_escalation_preserves_confirmation_confidence_and_image(self):
        row=self.record();self.event.update(severity='critical',state='critical');self.det['confidence']=.99
        self.record();current=self.repo.get(row['incident_id'])
        self.assertEqual(current['severity'],'critical');self.assertEqual(current['confidence'],.93)
        self.assertEqual(current['snapshot_sha256'],row['snapshot_sha256']);self.assertEqual(len(self.repo.transitions(row['incident_id'])),2)

    def test_concurrent_same_event_and_distinct_events(self):
        data=dict(source_event_key='same-key',event_id='SED2-1',timestamp=utc(),camera_id='cam',camera_location='Bay',
            class_id=7,class_name='chemical hazard',confidence=.9,severity='warning',bbox_x1=0,bbox_y1=0,bbox_x2=20,bbox_y2=20,image_width=100,image_height=100)
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results=list(pool.map(lambda _:self.repo.reserve(dict(data)),range(12)))
            self.assertEqual(sum(created for row,created in results),1)
            list(pool.map(lambda n:self.repo.reserve({**data,'source_event_key':f'new-{n}'}),range(12)))
        self.assertEqual(len(self.repo.list()),13);self.assertEqual(len({r['incident_id'] for r in self.repo.list()}),13)

    def test_crop_edges_outside_tiny_and_invalid(self):
        box=lambda *v:dict(zip(('x1','y1','x2','y2'),v))
        self.assertEqual(crop_bounds(self.frame,box(-20,-10,20,20)),(0,0,64,64))
        self.assertEqual(crop_bounds(self.frame,box(639,359,640,360)),(576,296,640,360))
        for coords in ((2,2,1,3),(800,0,900,100),(float('nan'),0,10,10)):
            with self.assertRaises(ValueError):crop_bounds(self.frame,box(*coords))

    def test_snapshot_failure_retains_row_then_recovers(self):
        with patch('Backend.incidents.service.write_snapshot',side_effect=OSError('Permission denied')):row=self.record()
        self.assertEqual(row['snapshot_status'],'failed');self.assertEqual(len(self.repo.list()),1)
        self.record();self.assertEqual(self.repo.get(row['incident_id'])['snapshot_status'],'ready')

    def test_database_failure_does_not_crash_detection_callback(self):
        with patch.object(self.repo,'reserve',side_effect=OSError('Database unavailable')):
            self.logger.observe(self.packet,self.result,self.camera)
        self.assertEqual(self.logger.failures,1);self.assertEqual(len(self.repo.list()),0)
        self.record();self.assertEqual(len(self.repo.list()),1)

    def test_pdf_content_images_signoff_and_readonly(self):
        row=self.record();before=self.repo.get(row['incident_id']);data,seconds=export_pdf(self.repo,row['incident_id'])
        pdf=PdfReader(io.BytesIO(data));text='\n'.join(page.extract_text() for page in pdf.pages)
        for value in (row['incident_id'],'WARNING','chemical hazard','Chemical Storage Bay','Signature','Corrective','SAMPLE / DEMONSTRATION'):
            self.assertIn(value,text)
        self.assertGreater(sum(len(page.images) for page in pdf.pages),0)
        self.assertEqual(before,self.repo.get(row['incident_id']));self.assertTrue(data.startswith(b'%PDF-'))

    def test_missing_corrupt_image_graceful(self):
        row=self.record();self.repo.snapshot_file(row).write_bytes(b'bad image')
        data,_=export_pdf(self.repo,row['incident_id'])
        self.assertIn('Evidence image unavailable','\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(data)).pages))
        self.repo.snapshot_file(row).unlink();export_pdf(self.repo,row['incident_id'])

    def test_invalid_id_sql_injection_and_path_traversal(self):
        for value in ("' OR 1=1--",'../../secret','INC-DOES-NOT-EXIST'):
            with self.assertRaises(ValueError):self.repo.get(value)
        with self.assertRaises(KeyError):export_pdf(self.repo,'INC-2026-999999')
        with self.assertRaises(ValueError):self.repo.snapshot_file(dict(snapshot_path='../events.db'))

    def test_existing_unrelated_data_preserved_and_incompatible_schema_rejected(self):
        import sqlite3
        db=self.root/'old.db'
        with closing(sqlite3.connect(db)) as c,c:c.execute('CREATE TABLE old_data(value TEXT)');c.execute("INSERT INTO old_data VALUES ('retained')")
        IncidentRepository(db,self.repo.snapshots)
        with closing(sqlite3.connect(db)) as c:self.assertEqual(c.execute('SELECT value FROM old_data').fetchone()[0],'retained')
        other=self.root/'incompatible.db'
        with closing(sqlite3.connect(other)) as c,c:c.execute('CREATE TABLE incidents(value TEXT)');c.execute("INSERT INTO incidents VALUES ('retained')")
        with self.assertRaises(RuntimeError):IncidentRepository(other,self.repo.snapshots)
        with closing(sqlite3.connect(other)) as c:self.assertEqual(c.execute('SELECT value FROM incidents').fetchone()[0],'retained')

    def test_offline_creation_and_export_block_all_socket_connects(self):
        with patch.object(socket.socket,'connect',side_effect=AssertionError('Network forbidden')),patch('socket.create_connection',side_effect=AssertionError('Network forbidden')):
            row=self.record();data,_=export_pdf(self.repo,row['incident_id'])
        self.assertTrue(data.startswith(b'%PDF-'))

    def test_pdf_escapes_untrusted_markup_and_flows_long_text(self):
        row=self.record()
        with self.repo.connect() as db:db.execute('UPDATE incidents SET operator_notes=? WHERE incident_id=?',('<script>Not executable</script> '+('review notes '*300),row['incident_id']))
        pdf=PdfReader(io.BytesIO(export_pdf(self.repo,row['incident_id'])[0]))
        self.assertGreater(len(pdf.pages),1);self.assertIn('<script>',''.join(p.extract_text() for p in pdf.pages))

    def test_production_publish_hook_calls_audit_after_display(self):
        import Backend.main as main
        calls=[];manager=SimpleNamespace(cameras={self.camera.camera_id:self.camera},scheduler_thread=SimpleNamespace(is_alive=lambda:False))
        fake=SimpleNamespace(observe=lambda *args,**kw:calls.append('audit'))
        with patch.object(main,'STREAM_MANAGER',manager),patch.object(main,'get_incident_logger',return_value=fake),patch.object(main.DISPLAY_HUB,'publish',side_effect=lambda *a:calls.append('display')):
            main.publish_result(self.packet,self.result)
        self.assertEqual(calls,['display','audit'])

    def test_backend_process_declines_sdk_telemetry_without_user_setting_write(self):
        from Backend.offline_policy import configure_local_runtime
        configure_local_runtime()
        from openvino_telemetry import Telemetry
        self.assertFalse(Telemetry(app_name='audit-validation').consent)

class ApiTests(unittest.TestCase):
    setUp=AuditTests.setUp
    record=AuditTests.record
    def test_api_export_snapshot_unknown_id_and_persistent_history(self):
        import Backend.main as main
        import Backend.incidents.api as api
        row=self.record()
        async def check():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.api_app),base_url='http://test') as c:
                self.assertEqual((await c.get('/incidents')).json()['incidents'][0]['incident_id'],row['incident_id'])
                self.assertEqual((await c.get('/incidents/'+row['incident_id']+'/snapshot')).headers['content-type'],'image/jpeg')
                response=await c.post('/incidents/'+row['incident_id']+'/export')
                self.assertEqual(response.status_code,200);self.assertTrue(response.content.startswith(b'%PDF-'))
                self.assertIn('X-PDF-Generation-Ms'.lower(),response.headers)
                self.assertEqual((await c.get('/incidents/INC-2026-999999')).status_code,404)
                self.assertEqual((await c.get('/incidents/not-an-id')).status_code,422)
        with patch.object(api,'get_logger',return_value=self.logger):asyncio.run(check())

if __name__=='__main__':unittest.main()
