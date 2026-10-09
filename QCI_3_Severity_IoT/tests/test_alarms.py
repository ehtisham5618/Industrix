"""Real socket receiver tests and durable state/concurrency failure regressions."""
from datetime import datetime,timedelta,timezone
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import time
import pytest
from pydantic import ValidationError
from QCI_3_Severity_IoT.contracts import Config,Rule,Event,Resolve,WebhookConfig,Delivery,Status
from QCI_3_Severity_IoT.engine import AlarmEngine,ConflictError,CapacityError,transition,VALID_TRANSITIONS
from QCI_3_Severity_IoT.webhook import WebhookWorker
from QCI_3_Severity_IoT.mock_receiver import MockReceiver
from QCI_3_Severity_IoT.offline import loopback_only
from SED_2_Alert_Escalation.scripts.models import Severity,EventState

ROOT=Path(__file__).resolve().parents[2]
ACTUAL=json.loads((ROOT/'reports/qci2/test_predictions.json').read_text(encoding='utf-8'))
NORMAL=next(r['prediction'] for r in ACTUAL if r['ground_truth']==0)
DEFECT=next(r['prediction'] for r in ACTUAL if r['ground_truth']==1)
NOW=datetime.now(timezone.utc)

def event(name='e1',source='camera1',seq=0,at=0,pred=DEFECT):
    return Event(source_id=source,event_id=name,sequence=seq,observed_at=NOW+timedelta(seconds=at),prediction=pred)

@pytest.fixture
def engine(tmp_path):return AlarmEngine(Config(database=str(tmp_path/'events.db')))

def critical(tmp_path,mock=None,**values):
    config=Config(database=str(tmp_path/'critical.db'),rules={'normal':Rule(initial='info'),
        'defect':Rule(initial='critical')},webhook=WebhookConfig(enabled=mock is not None,
        url=mock.url if mock else None,receiver_idempotent=True,timeout_seconds=.5,backoff_seconds=0),**values)
    return AlarmEngine(config)

@pytest.mark.parametrize('before,after',[(b,a) for b,v in VALID_TRANSITIONS.items() for a in v])
def test_valid_transitions(before,after):assert transition(before,after)==after

@pytest.mark.parametrize('before,after',[(b,a) for b in EventState for a in EventState if a not in VALID_TRANSITIONS[b]])
def test_invalid_transitions(before,after):
    with pytest.raises(ConflictError):transition(before,after)

def test_real_contract_defaults_and_serialization(engine):
    info=engine.process(event('normal',pred=NORMAL));warning=engine.process(event())
    assert info.severity==Severity.INFO and warning.severity==Severity.WARNING
    assert info.actions==['log','dashboard_info'];assert warning.actions==['log','dashboard_warning']
    assert Status.model_validate_json(warning.model_dump_json())==warning
    assert warning.model_version==DEFECT['model_version']

def test_duplicate_persists_without_duplicate_actions(engine):
    first=engine.process(event());again=AlarmEngine(engine.config).process(event())
    assert again.duplicate and again.actions==[]
    with engine.connect() as db:assert db.execute('SELECT COUNT(*) FROM qci3_audit').fetchone()[0]==1

def test_flicker_escalation_resolution_recurrence(tmp_path):
    e=AlarmEngine(Config(database=str(tmp_path/'a.db'),rules={'normal':Rule(initial='info'),
        'defect':Rule(initial='warning',critical_after_seconds=2)}))
    p=dict(NORMAL);p['sample_id']=DEFECT['sample_id']
    assert e.process(event(pred=p)).state==EventState.INFO
    assert e.process(event(seq=1,at=1)).state==EventState.WARNING
    assert e.process(event(seq=2,at=2)).state==EventState.CRITICAL
    result=e.process(event(seq=3,at=3,pred=p));assert result.state==EventState.CRITICAL and result.actions==[]
    r=Resolve(source_id='camera1',event_id='e1',observed_at=NOW+timedelta(seconds=4))
    assert e.resolve(r).state==EventState.RESOLVED
    assert e.resolve(r).duplicate
    with pytest.raises(ConflictError):e.process(event(seq=4,at=5))
    assert e.process(event(name='recurrence',at=5)).state==EventState.WARNING

def test_info_to_critical_source_override(tmp_path):
    e=AlarmEngine(Config(database=str(tmp_path/'a.db'),rules={'normal':Rule(initial='info'),
        'defect':Rule(initial='warning',source_overrides={'camera1':'critical'})}))
    p=dict(NORMAL);p['sample_id']=DEFECT['sample_id']
    e.process(event(pred=p));assert e.process(event(seq=1,at=1)).state==EventState.CRITICAL

def test_disabled_never_calls_transport(tmp_path,monkeypatch):
    e=critical(tmp_path);w=WebhookWorker(e)
    monkeypatch.setattr(w,'_send',lambda _:pytest.fail('Disabled transport called'))
    assert e.process(event()).delivery==Delivery.DISABLED;assert not w.run_once()

@pytest.mark.parametrize('codes,ack,delay,drop,expected,requests',[
    ((200,),True,0,False,Delivery.ACKNOWLEDGED,1),
    ((500,200),True,0,False,Delivery.ACKNOWLEDGED,2),
    ((500,),True,0,False,Delivery.FAILED,3),
    ((400,),True,0,False,Delivery.FAILED,1),
    ((302,),True,0,False,Delivery.DELIVERY_UNKNOWN,1),
    ((200,),False,0,False,Delivery.DELIVERY_UNKNOWN,1),
    ((200,),True,.75,False,Delivery.DELIVERY_UNKNOWN,3),
    ((200,),True,0,True,Delivery.DELIVERY_UNKNOWN,3)])
def test_actual_http_failure_matrix(tmp_path,codes,ack,delay,drop,expected,requests):
    with MockReceiver(codes,ack,delay,drop) as mock,loopback_only() as external:
        e=critical(tmp_path,mock);w=WebhookWorker(e);s=e.process(event())
        for _ in range(3):w.run_once()
        assert e.get('camera1','e1').delivery==expected
        assert e.get('camera1','e1').state==EventState.CRITICAL
        for _ in range(10):assert e.process(event()).duplicate
        assert len(mock.received)==requests;assert len(mock.activations)<=1
        assert all(r['idempotency_key']==s.delivery_id for r in mock.received)
        assert external==[]

def test_unreachable_endpoint_and_other_events_continue(tmp_path):
    with MockReceiver() as mock:url=mock.url
    c=Config(database=str(tmp_path/'a.db'),rules={'normal':Rule(initial='info'),'defect':Rule(initial='critical')},
        webhook=WebhookConfig(enabled=True,url=url,receiver_idempotent=True,timeout_seconds=.05,backoff_seconds=0))
    e=AlarmEngine(c);w=WebhookWorker(e);e.process(event())
    for _ in range(3):w.run_once()
    assert e.get('camera1','e1').delivery==Delivery.DELIVERY_UNKNOWN
    assert e.process(event('new',pred=NORMAL)).severity==Severity.INFO

def test_concurrent_duplicate_sources(tmp_path):
    e=critical(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as pool:result=list(pool.map(lambda _:e.process(event()),range(32)))
    assert sum(not s.duplicate for s in result)==1
    assert e.process(event(source='camera2')).source_id=='camera2'

def test_capacity_preserves_critical(tmp_path):
    e=critical(tmp_path,active_capacity=1)
    e.process(event())
    with pytest.raises(CapacityError):e.process(event('e2'))
    assert e.get('camera1','e1').state==EventState.CRITICAL

def test_outbox_capacity_explicit_local_failure(tmp_path):
    with MockReceiver() as mock:
        e=critical(tmp_path,mock,outbox_capacity=1);e.process(event())
        second=e.process(event('e2'));assert second.state==EventState.CRITICAL and second.delivery==Delivery.FAILED

def test_ttl_cleanup_replay_tombstone(tmp_path):
    current=[NOW.timestamp()]
    e=AlarmEngine(Config(database=str(tmp_path/'a.db'),resolved_ttl_seconds=1),clock=lambda:current[0])
    e.process(event());e.resolve(Resolve(source_id='camera1',event_id='e1',observed_at=NOW))
    current[0]+=2;assert e.snapshot()['resolved']==0
    with pytest.raises(ConflictError):e.process(event())
    assert e.process(event('new',at=3)).state==EventState.WARNING

def test_resolve_cancels_unsent_activation(tmp_path):
    with MockReceiver() as mock:
        e=critical(tmp_path,mock);w=WebhookWorker(e);e.process(event())
        e.resolve(Resolve(source_id='camera1',event_id='e1',observed_at=NOW))
        assert not w.run_once() and mock.received==[]
        assert e.get('camera1','e1').delivery==Delivery.FAILED

def test_crash_lease_retry_same_identity(tmp_path):
    with MockReceiver() as mock:
        e=critical(tmp_path,mock);w=WebhookWorker(e);s=e.process(event())
        with e.connect() as db:db.execute("UPDATE qci3_outbox SET state='IN_FLIGHT',lease=0,attempts=1")
        assert w.run_once();assert e.get('camera1','e1').delivery==Delivery.ACKNOWLEDGED
        assert mock.received[0]['idempotency_key']==s.delivery_id

def test_policy_change_requires_review(engine):
    c=engine.config.model_dump();c['policy_version']='changed'
    with pytest.raises(ConflictError):AlarmEngine(c)

@pytest.mark.parametrize('change',[{'sequence':True},{'event_id':''},{'source_id':'../oops'},
    {'observed_at':'2026-10-09T00:00:00'},{'extra':True}])
def test_bad_envelope(change):
    data=event().model_dump();data.update(change)
    with pytest.raises(ValidationError):Event.model_validate(data)

@pytest.mark.parametrize('url',['https://example.com/siren','http://8.8.8.8/siren',
    'http://user:password@127.0.0.1/a','file:///siren','http://127.0.0.1/a?token=x'])
def test_bad_endpoint(url):
    with pytest.raises(ValidationError):WebhookConfig(enabled=True,url=url)

def test_failed_prediction_and_wrong_model(engine):
    data=event().model_dump();data['prediction']={'status':'FAILED','sample_id':'bad'}
    with pytest.raises(ValidationError):Event.model_validate(data)
    data=event().model_dump();data['prediction']['model_version']='unknown'
    with pytest.raises(ConflictError):engine.process(data)

def test_out_of_order_and_conflicting_sequence(engine):
    engine.process(event(seq=2,at=2))
    for bad in (event(seq=1,at=3),event(seq=3,at=1),event(seq=2,at=4)):
        with pytest.raises(ConflictError):engine.process(bad)

def test_worker_lifecycle_nonblocking_local_path(tmp_path):
    with MockReceiver(delay=.75) as mock:
        e=critical(tmp_path,mock);w=WebhookWorker(e);w.start()
        try:
            e.process(event());assert e.process(event('info',pred=NORMAL)).state==EventState.INFO
            deadline=time.monotonic()+4
            while e.get('camera1','e1').delivery==Delivery.PENDING and time.monotonic()<deadline:time.sleep(.02)
            assert e.get('camera1','e1').delivery==Delivery.DELIVERY_UNKNOWN
        finally:w.stop()
        assert not w.thread.is_alive()

def test_api_contract_and_conflict_status(engine,monkeypatch):
    import asyncio
    import httpx
    from fastapi import FastAPI
    from QCI_3_Severity_IoT import api
    monkeypatch.setattr(api,'service',lambda:(engine,None))
    app=FastAPI();app.include_router(api.router)
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            assert (await client.post('/qci3/events',json=event().model_dump(mode='json'))).status_code==200
            bad=event(seq=0,at=1).model_dump(mode='json')
            assert (await client.post('/qci3/events',json=bad)).status_code==409
            assert (await client.get('/qci3/status')).json()['active']==1
            assert (await client.post('/qci3/events',json={})).status_code==422
            assert (await client.post('/qci3/events',content=b'x'*65537)).status_code==413
    asyncio.run(check())

def test_transport_auth_not_logged(tmp_path,monkeypatch):
    monkeypatch.setenv('QCI3_SIREN_TOKEN','test-only-fake-token')
    with MockReceiver(codes=(400,)) as mock:
        e=critical(tmp_path,mock);e.process(event());WebhookWorker(e).run_once()
        with e.connect() as db:
            logs=' '.join(str(tuple(r)) for r in db.execute('SELECT * FROM qci3_audit'))
            logs+=' '.join(str(tuple(r)) for r in db.execute('SELECT * FROM qci3_outbox'))
        assert 'test-only-fake-token' not in logs

def test_prediction_limits_and_sample_identity(engine):
    data=event().model_dump();data['prediction']['warnings']=['warning']*17
    with pytest.raises(ValidationError):Event.model_validate(data)
    engine.process(event());data=event(seq=1,at=1).model_dump();data['prediction']['sample_id']='different.jpg'
    with pytest.raises(ConflictError):engine.process(data)

def test_invalid_rules_and_retry_contract():
    with pytest.raises(ValidationError):Rule(initial='warning',warning_after_seconds=5,critical_after_seconds=2)
    with pytest.raises(ValidationError):Config(rules={'defect':Rule(initial='warning')})
    with pytest.raises(ValidationError):WebhookConfig(enabled=True,url='http://127.0.0.1/siren',receiver_idempotent=False)

def test_duplicate_json_rules_rejected():
    from QCI_3_Severity_IoT.contracts import parse_config
    with pytest.raises(ValueError):parse_config('{"rules":{},"rules":{}}')

def test_two_workers_claim_one_activation(tmp_path):
    with MockReceiver() as mock:
        e=critical(tmp_path,mock);e.process(event())
        workers=[WebhookWorker(e),WebhookWorker(AlarmEngine(e.config))]
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(lambda w:w.run_once(),workers))
        assert len(mock.received)==1 and len(mock.activations)==1

def test_untrusted_retry_receiver_crash_is_unknown(tmp_path):
    with MockReceiver() as mock:
        c=Config(database=str(tmp_path/'a.db'),rules={'normal':Rule(initial='info'),'defect':Rule(initial='critical')},
            webhook=WebhookConfig(enabled=True,url=mock.url,attempts=1,receiver_idempotent=False))
        e=AlarmEngine(c);e.process(event())
        with e.connect() as db:db.execute("UPDATE qci3_outbox SET state='IN_FLIGHT',lease=0,attempts=1")
        assert not WebhookWorker(e).run_once()
        assert e.get('camera1','e1').delivery==Delivery.DELIVERY_UNKNOWN and not mock.received

def test_concurrent_api_first_requests_create_one_service(tmp_path,monkeypatch):
    from QCI_3_Severity_IoT import api
    config=tmp_path/'config.json';config.write_text(Config(database=str(tmp_path/'a.db')).model_dump_json())
    monkeypatch.setenv('QCI3_CONFIG',str(config));api.shutdown()
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:instances=list(pool.map(lambda _:api.service(),range(32)))
        assert len({id(pair[0]) for pair in instances})==1
        assert len({id(pair[1]) for pair in instances})==1
    finally:api.shutdown()
