"""Real loopback HTTP plus durable queue, privacy, restart and worker regressions."""
from collections import deque
from datetime import datetime,timezone,timedelta
from concurrent.futures import ThreadPoolExecutor
import gc
import json
from pathlib import Path
import sqlite3
import time
import pytest
from pydantic import ValidationError
from QCI_4_Edge_Telemetry.contracts import Config,TelemetryPayload,EventPayload,Snapshot,CloudStatus,Mode,SyncState,parse_config
from QCI_4_Edge_Telemetry.spool import Spool,OverflowError,DedupeConflict
from QCI_4_Edge_Telemetry.cloud import SyncWorker,CloudClient
from QCI_4_Edge_Telemetry.collector import Collector
from QCI_4_Edge_Telemetry.inference import InferenceTracker
from QCI_4_Edge_Telemetry.mock_cloud import MockCloud
from QCI_3_Severity_IoT.offline import loopback_only
from QCI_3_Severity_IoT.engine import AlarmEngine
from QCI_3_Severity_IoT.contracts import Config as AlarmConfig,Rule,Event,Resolve
from QCI_2_Defect_Classifier.contracts import PredictionResult

ROOT=Path(__file__).resolve().parents[2];NOW=datetime.now(timezone.utc)
PREDICTIONS=json.loads((ROOT/'reports/qci2/test_predictions.json').read_text())
DEFECT=next(r['prediction'] for r in PREDICTIONS if r['ground_truth']==1)

def config(tmp_path,mock=None,**kwargs):
    values=dict(database=str(tmp_path/'edge.db'),alerts_database=str(tmp_path/'edge.db'),minimum_disk_free_bytes=0)
    if mock:values.update(cloud_enabled=True,cloud_base_url=mock.url,health_path='/health',sync_path='/sync',
        allow_telemetry_sync=True,allow_event_sync=True,receiver_idempotent=True,request_timeout_seconds=.5,
        backoff_base_seconds=.01,backoff_max_seconds=2,jitter_fraction=0,replay_items_per_second=100,health_interval_seconds=.1)
    values.update(kwargs);return Config(**values)

def payload(at=NOW):return TelemetryPayload(observed_at=at,cpu_percent=25,ram_percent=50,process_rss_mb=42,
    disk_used_percent=60,inference_count=1,inference_latency_ms=12,active_alerts=0,edge_status='HEALTHY')
def event_payload(sequence=1,state='critical',severity='critical',at=NOW,activation='a'*64):
    return EventPayload(observed_at=at,activation_key=activation,transition_sequence=sequence,state=state,severity=severity,
        model_version='qci2-kolektor-resnet18-v1',policy_version='qci3-research-v1')

def advance(worker,seconds=3):
    worker.next_health=0;worker.next_send=0
    with worker.spool.connect() as db:db.execute('UPDATE qci4_spool SET due=0')

def test_disabled_no_http_or_spool(tmp_path,monkeypatch):
    s=Spool(config(tmp_path));w=SyncWorker(s)
    monkeypatch.setattr(w.client,'request',lambda *args,**kw:pytest.fail('Disabled HTTP'))
    assert s.enqueue('routine',payload()) is None and not w.tick()
    w.start();assert w.thread is None
    assert w.snapshot().status==CloudStatus.DISABLED and s.stats().pending==0

def test_real_structured_telemetry_unknown_pipeline(tmp_path):
    s=Spool(config(tmp_path));c=Collector(s.config,s,SyncWorker(s),tracker=InferenceTracker())
    first=c.sample();second=c.sample()
    assert first.resources.cpu_percent is None
    assert second.resources.ram_used_mb>0 and second.resources.process_rss_mb>0
    assert 0<=second.resources.disk_used_percent<=100 and second.resources.disk_free_bytes>=0
    assert second.inference.model_loaded is None and second.alerts.active_critical is None
    assert Snapshot.model_validate_json(second.model_dump_json())==second

@pytest.mark.parametrize('change',[
    {'cloud_enabled':True},{'spool_max_items':0},{'sample_interval_seconds':0},
    {'database':'https://example.com/db'},{'cloud_base_url':'http://8.8.8.8'},
    {'cloud_base_url':'https://user:secret@1.1.1.1'},{'cloud_base_url':'https://example.com'},
    {'request_timeout_seconds':float('nan')},{'backoff_base_seconds':5,'backoff_max_seconds':1}])
def test_invalid_config(change):
    with pytest.raises(ValidationError):Config(**change)

def test_duplicate_config_keys():
    with pytest.raises(ValueError):parse_config('{"cloud_enabled":false,"cloud_enabled":true}')

def test_outbound_privacy_allowlist(tmp_path):
    data=payload().model_dump();data['raw_image']='secret.png'
    with pytest.raises(ValidationError):TelemetryPayload.model_validate(data)
    data=event_payload().model_dump();data['source_id']='private-camera-name'
    with pytest.raises(ValidationError):EventPayload.model_validate(data)

def test_online_expected_ack_and_dedupe(tmp_path):
    with MockCloud(tmp_path/'receiver.db') as m,loopback_only() as external:
        s=Spool(config(tmp_path,m));w=SyncWorker(s);p=payload();item=s.enqueue('one',p)
        assert w.tick() and w.snapshot().status==CloudStatus.ONLINE
        assert s.stats().delivered_total==1 and s.stats().pending==0
        assert s.enqueue('one',p)==item and not w.tick()
        assert len(m.receipts())==1 and len(m.attempts)==1 and external==[]
        assert w.snapshot().last_successful_sync is not None

def test_dropout_restart_recovery_while_real_alarm_preserved(tmp_path):
    with MockCloud(tmp_path/'receiver.db') as m,loopback_only():
        c=config(tmp_path,m);s=Spool(c);w=SyncWorker(s);assert not w.tick() and w.snapshot().status==CloudStatus.ONLINE
        m.health_online=False;advance(w);w.tick();advance(w);w.tick()
        assert w.snapshot().status==CloudStatus.OFFLINE and w.snapshot().mode==Mode.LOCAL_ONLY
        alarm=AlarmEngine(AlarmConfig(database=c.alerts_database,rules={'normal':Rule(initial='info'),'defect':Rule(initial='critical')}))
        result=alarm.process(Event(source_id='local',event_id='outage',sequence=0,observed_at=NOW,prediction=DEFECT))
        assert result.state.value=='critical'
        collector=Collector(c,s,w,tracker=InferenceTracker());collector.sample()
        assert s.stats().pending==2 and alarm.get('local','outage').state.value=='critical'
        restarted=Spool(c);recovery=SyncWorker(restarted);assert recovery.snapshot().status==CloudStatus.UNKNOWN
        m.health_online=True;assert recovery.tick();recovery.next_send=0;assert recovery.tick()
        assert restarted.stats().pending==0 and len(m.receipts())==2
        assert recovery.snapshot().status==CloudStatus.ONLINE

@pytest.mark.parametrize('code,expected,attempts',[(500,SyncState.FAILED_PERMANENT,3),(429,SyncState.FAILED_PERMANENT,3),
    (400,SyncState.FAILED_PERMANENT,1),(302,SyncState.FAILED_PERMANENT,1)])
def test_http_retry_matrix(tmp_path,code,expected,attempts):
    with MockCloud(tmp_path/'receiver.db') as m:
        m.codes=deque([code]);s=Spool(config(tmp_path,m));w=SyncWorker(s);item=s.enqueue('one',event_payload())
        for _ in range(3):advance(w);w.tick()
        assert s.item(item)['state']==expected.value and len(m.attempts)==attempts
        assert w.snapshot().mode==Mode.LOCAL_ONLY and w.snapshot().health_check_status=='ONLINE'

@pytest.mark.parametrize('mode',['bad_ack','malformed','oversized','drop','timeout'])
def test_unknown_response_never_delivered(tmp_path,mode):
    with MockCloud(tmp_path/'receiver.db') as m:
        s=Spool(config(tmp_path,m));w=SyncWorker(s);item=s.enqueue('one',event_payload())
        # Establish genuine endpoint health before injecting an upload-only fault.
        w.tick();assert s.stats().delivered_total==1
        item=s.enqueue('two',event_payload(sequence=2,activation='b'*64))
        if mode=='timeout':m.delay=.75
        else:setattr(m,mode,True)
        for _ in range(3):w.next_send=0;w.next_health=time.time()+10;w.tick();advance_due(s)
        assert s.stats().delivered_total==1 and s.item(item)['state'] in ('DELIVERY_UNKNOWN','FAILED_PERMANENT')
        assert len(m.receipts())<=2

def advance_due(spool):
    with spool.connect() as db:db.execute('UPDATE qci4_spool SET due=0')

def test_429_retry_after_is_capped_and_respected(tmp_path):
    with MockCloud(tmp_path/'receiver.db') as m:
        m.codes=deque([429]);m.retry_after='99999';s=Spool(config(tmp_path,m));w=SyncWorker(s);item=s.enqueue('one',payload())
        before=time.time();w.tick();assert s.item(item)['due']>=before+1.9
        assert not w.tick() and len(m.attempts)==1

def test_missing_cloud_connection_refused_preserves_queue(tmp_path):
    with MockCloud(tmp_path/'receiver.db') as m:url=m.url
    c=config(tmp_path);values=c.model_dump();values.update(cloud_enabled=True,cloud_base_url=url,health_path='/health',sync_path='/sync',allow_event_sync=True,receiver_idempotent=True)
    s=Spool(Config.model_validate(values));s.enqueue('one',event_payload());w=SyncWorker(s);w.tick()
    assert s.stats().pending==1 and w.snapshot().mode==Mode.LOCAL_ONLY

def test_critical_preempts_unsent_routine_capacity(tmp_path):
    with MockCloud(tmp_path/'receiver.db') as m:
        s=Spool(config(tmp_path,m,spool_max_items=1));s.enqueue('routine',payload());s.enqueue('critical',event_payload())
        assert s.stats().owned_rows==1 and s.stats().routine_skipped_total==1
        with pytest.raises(OverflowError):s.enqueue('another-critical',event_payload(2,activation='b'*64))
        assert s.stats().overflow_total==1

def test_byte_budget_and_disk_reserve(tmp_path):
    with MockCloud(tmp_path/'receiver.db') as m:
        s=Spool(config(tmp_path,m,spool_max_payload_bytes=1024,item_max_bytes=1024,minimum_disk_free_bytes=10**12))
        with pytest.raises(OverflowError):s.enqueue('event',event_payload())
        assert s.stats().pending==0 and s.stats().overflow_total==1

def test_immutable_duplicate_and_thread_safety(tmp_path):
    with MockCloud(tmp_path/'receiver.db') as m:
        s=Spool(config(tmp_path,m));p=payload()
        with ThreadPoolExecutor(max_workers=8) as pool:ids=list(pool.map(lambda _:s.enqueue('same',p),range(20)))
        assert len(set(ids))==1 and s.stats().pending==1
        with pytest.raises(DedupeConflict):s.enqueue('same',payload(NOW+timedelta(seconds=1)))

def test_ordered_transitions_block_resolution_before_critical(tmp_path):
    with MockCloud(tmp_path/'receiver.db') as m:
        s=Spool(config(tmp_path,m));first=s.enqueue('critical',event_payload());resolved=s.enqueue('resolved',event_payload(2,'resolved'))
        row=s.claim();assert row['id']==first
        s.complete(row,SyncState.FAILED_RETRYABLE,'temporary',500,time.time()+100)
        assert s.claim() is None
        with s.connect() as db:db.execute('UPDATE qci4_spool SET due=0')
        row=s.claim();s.complete(row,SyncState.DELIVERED)
        assert s.claim()['id']==resolved

def test_routine_expiry_but_critical_retained(tmp_path):
    with MockCloud(tmp_path/'receiver.db') as m:
        now=[NOW.timestamp()];s=Spool(config(tmp_path,m,routine_ttl_seconds=1),clock=lambda:now[0])
        s.enqueue('routine',payload());s.enqueue('event',event_payload());now[0]+=2
        assert s.stats().owned_rows==1 and s.stats().routine_expired_total==1

def test_restart_recovers_dispatch_lease_without_duplicate_receipt(tmp_path):
    with MockCloud(tmp_path/'receiver.db') as m:
        c=config(tmp_path,m);s=Spool(c);item=s.enqueue('one',event_payload());row=s.claim()
        valid,result=CloudClient(c).send(row);assert valid
        with s.connect() as db:db.execute('UPDATE qci4_spool SET lease=0')
        restarted=Spool(c);worker=SyncWorker(restarted);assert worker.tick()
        assert restarted.stats().delivered_total==1 and len(m.receipts())==1 and len(m.attempts)==2

def test_receipt_retention_rejects_old_replays(tmp_path):
    with MockCloud(tmp_path/'receiver.db') as m:
        now=[NOW.timestamp()];s=Spool(config(tmp_path,m,receipt_ttl_seconds=1),clock=lambda:now[0]);s.enqueue('one',payload())
        row=s.claim();s.complete(row,SyncState.DELIVERED);now[0]+=2;assert s.stats().receipt_rows==0
        with pytest.raises(DedupeConflict):s.enqueue('one',payload())

def test_event_collection_cursor_durable_and_no_private_identifiers(tmp_path):
    with MockCloud(tmp_path/'receiver.db') as m:
        c=config(tmp_path,m);s=Spool(c);w=SyncWorker(s);a=AlarmEngine(AlarmConfig(database=c.alerts_database))
        a.process(Event(source_id='private-camera',event_id='private-part',sequence=0,observed_at=NOW,prediction=DEFECT))
        a.resolve(Resolve(source_id='private-camera',event_id='private-part',observed_at=NOW+timedelta(seconds=1)))
        collector=Collector(c,s,w,tracker=InferenceTracker());collector.sample()
        assert s.stats().pending==3
        collector.sample();assert s.stats().pending==3
        with s.connect() as db:
            values=' '.join(r[0] for r in db.execute('SELECT payload FROM qci4_spool'))
        assert 'private-camera' not in values and 'private-part' not in values and 'heatmap' not in values
        assert collector.alert_health().active_warning==0

def test_worker_and_sampler_stop_without_accumulation(tmp_path):
    with MockCloud(tmp_path/'receiver.db') as m:
        s=Spool(config(tmp_path,m,sample_interval_seconds=.1));w=SyncWorker(s);c=Collector(s.config,s,w,tracker=InferenceTracker())
        for _ in range(3):
            c.start();w.start();time.sleep(.12);c.stop();w.stop()
            assert not c.thread.is_alive() and not w.thread.is_alive()
            assert c.latest is not None
        assert len(c.history)<=c.config.history_capacity

def test_inference_tracker_bounded_weak_reference_and_errors():
    class LocalFixture:
        model=object();metadata={'model_version':'unit-model'};error=None
    fixture=LocalFixture();t=InferenceTracker(capacity=4);t.bind(fixture)
    p=PredictionResult.model_validate(DEFECT)
    for _ in range(10):t.observe(p)
    h=t.snapshot();assert h.model_loaded and h.inference_count==10 and h.recent_samples==4
    t.observe(PredictionResult(status='FAILED',sample_id='bad',error_type='ValueError',error_message='private-path'))
    assert t.snapshot().last_error=='ValueError'
    del fixture;gc.collect();assert t.snapshot().model_status=='UNLOADED'

def test_policy_change_does_not_reinterpret_pending_items(tmp_path):
    with MockCloud(tmp_path/'receiver.db') as m:
        c=config(tmp_path,m);Spool(c);values=c.model_dump();values['attempts']=4
        with pytest.raises(DedupeConflict):Spool(Config.model_validate(values))

def test_api_typed_status_without_cloud_work(tmp_path,monkeypatch):
    import asyncio,httpx
    from fastapi import FastAPI
    from QCI_4_Edge_Telemetry import api
    svc=api.EdgeService(config(tmp_path));monkeypatch.setattr(api,'service',lambda:svc)
    monkeypatch.setattr(svc.worker.client,'request',lambda *args,**kw:pytest.fail('GET status invoked cloud'))
    app=FastAPI();app.include_router(api.router)
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://unit') as client:
            response=await client.get('/edge/status');assert response.status_code==200
            assert response.json()['cloud']['status']=='DISABLED'
            assert (await client.get('/edge/history?limit=1000')).status_code==422
    asyncio.run(check())

def test_real_classifier_alarms_continue_with_failed_cloud(tmp_path):
    import cv2,numpy as np
    cv2.setNumThreads(1);cv2.resize(np.zeros((2,2),np.float32),(3,3))
    from QCI_2_Defect_Classifier.common import deterministic
    from QCI_2_Defect_Classifier.infer import DefectClassifier
    deterministic();tracker=InferenceTracker()
    records=[json.loads(line) for line in (ROOT/'reports/qci1/segmentation/samples.jsonl').read_text().splitlines()]
    sample=next(r for r in PREDICTIONS if r['ground_truth']==1)
    record=next(r for r in records if r['sample_id']==sample['sample_id'])
    image=ROOT/'QCI_1_Surface_Defect_Segmentation/runtime/segmentation_dataset'/record['image']['path']
    with MockCloud(tmp_path/'receiver.db') as m,loopback_only():
        m.health_online=False;c=config(tmp_path,m);s=Spool(c);w=SyncWorker(s);w.tick()
        classifier=DefectClassifier(ROOT/'QCI_2_Defect_Classifier/runtime/run_v1/best.pt',
            '00f626cf837139c3476dd4f2c77b4b0a8faa7e4b368af13936b33ddca838b795',telemetry=tracker)
        result=classifier.predict({'image':str(image),'heatmap':True})
        assert result.status=='SUCCESS' and result.heatmap is not None
        assert abs(result.confidence-sample['prediction']['confidence'])<1e-6
        assert tracker.snapshot().model_loaded and tracker.snapshot().inference_count==1
        alarm=AlarmEngine(AlarmConfig(database=c.alerts_database,rules={'normal':Rule(initial='info'),'defect':Rule(initial='critical')}))
        alarm.process(Event(source_id='real-test',event_id='during-outage',sequence=0,observed_at=datetime.now(timezone.utc),prediction=result))
        snapshot=Collector(c,s,w,tracker=tracker).sample()
        assert snapshot.inference.status=='HEALTHY' and snapshot.alerts.active_critical==1
        assert not snapshot.local_ai_requires_cloud and s.stats().pending==2

def test_monitor_failure_cannot_change_prediction_failure(tmp_path):
    class BrokenObserver:
        def bind(self,*args):raise RuntimeError('unit observer failure')
        def observe(self,*args):raise RuntimeError('unit observer failure')
    from QCI_2_Defect_Classifier.infer import DefectClassifier
    classifier=DefectClassifier(tmp_path/'missing.pt',telemetry=BrokenObserver())
    result=classifier.predict({'image':str(tmp_path/'missing.jpg')})
    assert result.status=='FAILED' and result.error_type!='unit observer failure'

def test_disabling_cloud_preserves_pending_and_reenables_same_policy(tmp_path):
    with MockCloud(tmp_path/'receiver.db') as m:
        c=config(tmp_path,m);s=Spool(c);s.enqueue('one',event_payload())
        paused=c.model_copy(update={'cloud_enabled':False,'cloud_base_url':None,'health_path':None,'sync_path':None})
        disabled=Spool(paused);assert disabled.stats().pending==1
        assert not SyncWorker(disabled).tick()
        assert SyncWorker(Spool(c)).tick()

def test_trickled_headers_obey_absolute_deadline(tmp_path):
    with MockCloud(tmp_path/'receiver.db') as m:
        c=config(tmp_path,m,request_timeout_seconds=.2);s=Spool(c);s.enqueue('one',event_payload());row=s.claim()
        m.trickle_headers=.02;started=time.monotonic();valid,response=CloudClient(c).send(row)
        assert not valid and response.error=='transport_outcome_unknown'
        assert time.monotonic()-started<.6

def test_batch_capacity_preserves_critical_and_cursor_prefix(tmp_path):
    with MockCloud(tmp_path/'receiver.db') as m:
        c=config(tmp_path,m,spool_max_items=1,allow_telemetry_sync=False);s=Spool(c);w=SyncWorker(s)
        a=AlarmEngine(AlarmConfig(database=c.alerts_database,rules={'normal':Rule(initial='info'),'defect':Rule(initial='critical')}))
        a.process(Event(source_id='actual',event_id='activation',sequence=0,observed_at=NOW,prediction=DEFECT))
        a.resolve(Resolve(source_id='actual',event_id='activation',observed_at=NOW+timedelta(seconds=1)))
        collector=Collector(c,s,w,tracker=InferenceTracker());snapshot=collector.sample()
        assert snapshot.error_categories==['spool_capacity_reached']
        assert s.get_meta('alert_cursor')=='1' and s.stats().pending==1 and s.stats().overflow_total==1
        assert w.tick();collector.sample();advance(w);assert w.tick()
        assert [json.loads(row[3])['state'] for row in m.receipts()]==['critical','resolved']

def test_initial_disabled_store_can_enable_cloud(tmp_path):
    Spool(config(tmp_path))
    with MockCloud(tmp_path/'receiver.db') as m:
        enabled=Spool(config(tmp_path,m));enabled.enqueue('one',payload());assert SyncWorker(enabled).tick()

def test_cloud_secret_never_enters_database_or_status(tmp_path,monkeypatch):
    monkeypatch.setenv('INDUSRIX_CLOUD_TOKEN','unit-only-fake-secret')
    with MockCloud(tmp_path/'receiver.db') as m:
        c=config(tmp_path,m);s=Spool(c);s.enqueue('one',payload());w=SyncWorker(s);assert w.tick()
        with s.connect() as db:
            text=' '.join(str(tuple(r)) for r in db.execute('SELECT * FROM qci4_log'))
        assert 'unit-only-fake-secret' not in text+w.snapshot().model_dump_json()

def test_device_namespaces_prevent_cross_edge_dedupe_collisions(tmp_path):
    with MockCloud(tmp_path/'receiver.db') as m:
        left=Spool(config(tmp_path,m));second=tmp_path/'second';second.mkdir()
        right=Spool(config(second,m));left.enqueue('event:1',event_payload());right.enqueue('event:1',event_payload())
        assert SyncWorker(left).tick() and SyncWorker(right).tick()
        assert m.receipt_count()==2 and left.device_id!=right.device_id

def test_changed_alarm_source_cannot_silently_reuse_cursor(tmp_path):
    with MockCloud(tmp_path/'receiver.db') as m:
        c=config(tmp_path,m,allow_telemetry_sync=False);s=Spool(c);w=SyncWorker(s)
        first=AlarmEngine(AlarmConfig(database=c.alerts_database))
        first.process(Event(source_id='first',event_id='e1',sequence=0,observed_at=NOW,prediction=DEFECT))
        collector=Collector(c,s,w,tracker=InferenceTracker());collector.sample();assert s.get_meta('alert_cursor')=='1'
        other=tmp_path/'other.db';second=AlarmEngine(AlarmConfig(database=str(other)))
        second.process(Event(source_id='second',event_id='e1',sequence=0,observed_at=NOW,prediction=DEFECT))
        collector.alerts_path=other
        assert 'alarm_sync_collection_failed' in collector.sample().error_categories
        assert s.get_meta('alert_cursor')=='1' and s.stats().pending==1

def test_ephemeral_wal_stat_race_is_not_a_health_failure(tmp_path,monkeypatch):
    s=Spool(config(tmp_path));original=Path.stat
    def disappearing(path,*args,**kwargs):
        if str(path).endswith(('-wal','-shm')):raise FileNotFoundError('unit concurrent checkpoint')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'stat',disappearing)
    assert s.stats().database_bytes>0

def test_healthy_probes_do_not_fabricate_recovery_transitions(tmp_path):
    with MockCloud(tmp_path/'receiver.db') as m:
        s=Spool(config(tmp_path,m));w=SyncWorker(s);w.tick();w.tick(force_health=True)
        assert w.snapshot().status==CloudStatus.ONLINE
        with s.connect() as db:assert db.execute("SELECT COUNT(*) FROM qci4_log WHERE code='CLOUD_RECOVERED'").fetchone()[0]==0
