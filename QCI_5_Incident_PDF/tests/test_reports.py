import asyncio
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch
import httpx
from PIL import Image
from pypdf import PdfReader
import pytest
from Backend.incidents.repository import IncidentRepository
from QCI_3_Severity_IoT.contracts import Config as AlarmConfig, Event, Rule
from QCI_3_Severity_IoT.engine import AlarmEngine
from QCI_1_Surface_Defect_Segmentation.offline import no_network
from QCI_5_Incident_PDF.adapter import Adapter, ROOT, quality_id, identity
from QCI_5_Incident_PDF.contracts import Config, Evidence, ExportResult, ReportData, Telemetry
from QCI_5_Incident_PDF.service import PDFService, filename

def text(data):return '\n'.join(page.extract_text() for page in PdfReader(io.BytesIO(data)).pages)

@pytest.fixture
def service(tmp_path):
    p=json.loads((ROOT/'reports/qci2/test_predictions.json').read_text())[0]['prediction']
    engine=AlarmEngine(AlarmConfig(database=str(tmp_path/'events.db'),rules={
        'normal':Rule(initial='info'), 'defect':Rule(initial='warning')}))
    event=Event(source_id='test-source',event_id='test-event',sequence=0,
        observed_at=datetime.now(timezone.utc),prediction=p)
    engine.process(event)
    config=Config(quality_database=str(tmp_path/'events.db'),output_dir=str(tmp_path/'reports'),evidence_roots=[str(tmp_path)])
    return PDFService(Adapter(config=config)),quality_id(event.source_id,event.event_id),tmp_path

def read_result(result):
    assert result.status=='SUCCESS',result
    return Path(result.output_path).read_bytes()

def test_actual_qci3_record_pdf_contract_metadata_and_readonly(service):
    s,key,root=service
    before=s.adapter.database.read_bytes()
    result=s.generate(key);data=read_result(result);words=text(data)
    for item in (key,'INFO','normal',f'{s.adapter.load(key).confidence*100:.1f}%','qci2-kolektor-resnet18-v1','Signature','Pending operator review'):
        assert item in words
    pdf=PdfReader(io.BytesIO(data));assert len(pdf.pages)>=2
    assert all(abs(float(page.mediabox.width)-595.2756)<.1 for page in pdf.pages)
    assert pdf.metadata.author=='IndusriX' and 'IndusriX' in pdf.metadata.title
    assert before==s.adapter.database.read_bytes()
    assert ExportResult.model_validate_json(result.model_dump_json())==result
    assert result.sha256==hashlib.sha256(data).hexdigest() and result.size_bytes==len(data)

@pytest.mark.parametrize('severity',['info','warning','critical'])
def test_authoritative_severity_is_not_recomputed(service,severity):
    s,key,_=service;report=s.adapter.load(key);report.severity=severity
    data,_,_,_=s.render(report)
    assert severity.upper() in text(data)

@pytest.mark.parametrize('bad',['../../secret','INC-bad',"' OR 1=1--",'QCI3-abc','QCI3-../../file','QCI3-\nX',''])
def test_invalid_id_cannot_write_files(service,bad):
    s,_,root=service;result=s.generate(bad)
    assert result.status=='FAILED' and result.error=='INVALID_INPUT'
    assert not (root/'reports').exists()

def test_unknown_event_and_legacy_ids_do_not_create_empty_pdf(service):
    s,_,root=service
    assert s.generate(quality_id('test-source','unknown')).error=='NOT_FOUND'
    s.adapter.legacy=IncidentRepository(root/'events.db',root/'snapshots')
    assert s.generate('INC-2026-999999').error=='NOT_FOUND'
    assert not list(root.rglob('*.pdf'))

@pytest.mark.parametrize('bad',['../outside','https://cloud/pdf','//server/share','a/../../outside'])
def test_output_root_traversal_rejected(service,bad):
    s,key,root=service;s.config.output_dir=bad
    assert s.generate(key).error=='INVALID_INPUT'
    assert not list(root.rglob('*.pdf'))

def test_subdirectory_cannot_escape_root(service):
    s,key,root=service
    assert s.generate(key,'../secret').error=='INVALID_INPUT'
    assert s.generate(key,str(root/'outside')).error=='INVALID_INPUT'
    assert s.generate(key,'nested').status=='SUCCESS'

@pytest.mark.parametrize('kind',['valid','missing','corrupt','hash_mismatch','pixel_budget','byte_budget','outside_root'])
def test_bounded_evidence_and_graceful_warnings(service,kind):
    s,key,root=service;report=s.adapter.load(key);path=root/'evidence.png'
    with Image.new('RGB',(100,300),'#225577') as image:image.save(path)
    if kind=='missing':path.unlink()
    if kind=='corrupt':path.write_bytes(b'broken image')
    if kind=='pixel_budget':s.config.max_image_pixels=20
    if kind=='byte_budget':s.config.max_image_bytes=10
    if kind=='outside_root':s.config.evidence_roots=[str(root/'other')]
    report.evidence=[Evidence(role='Evidence image',path=str(path),sha256='0'*64 if kind=='hash_mismatch' else None)]
    before=path.read_bytes() if path.exists() else None
    data,warnings,_,_=s.render(report);pdf=PdfReader(io.BytesIO(data))
    if kind=='valid':assert sum(len(p.images) for p in pdf.pages)>0
    else:
        assert sum(len(p.images) for p in pdf.pages)==0
        assert 'Evidence image unavailable' in text(data)
        assert any(w.startswith('EVIDENCE_') for w in warnings)
    assert before==(path.read_bytes() if path.exists() else None)

def test_heatmap_label_and_disabled_option(service):
    s,key,root=service;path=root/'cam.png'
    with Image.new('RGB',(60,120),'red') as image:image.save(path)
    report=s.adapter.load(key);report.evidence=[Evidence(role='Model Attribution Heatmap',path=str(path))]
    data,_,_,_=s.render(report)
    assert 'Model Attribution Heatmap' in text(data) and 'Ground Truth' not in text(data)
    assert sum(len(p.images) for p in PdfReader(io.BytesIO(data)).pages)>0
    s.config.include_heatmap=False;data,_,_,_=s.render(report)
    assert sum(len(p.images) for p in PdfReader(io.BytesIO(data)).pages)==0

def test_long_notes_markup_unicode_and_all_text_preserved(service):
    s,key,_=service;report=s.adapter.load(key)
    report.operator_notes='<script>literal</script> café Ω 😀\n'+('Detailed operator note. '*1400)+'END-OF-NOTES'
    report.corrective_action=('Follow-up pending. '*700)+'END-OF-ACTION'
    data,warnings,_,_=s.render(report);words=text(data)
    assert len(PdfReader(io.BytesIO(data)).pages)>10
    for token in ('<script>literal</script>','café','Ω','[U+1F600]','END-OF-NOTES','END-OF-ACTION'):assert token in words
    assert any('FONT_UNSUPPORTED' in w for w in warnings)

def test_telemetry_time_and_siren_acknowledgement_are_explicit(service):
    s,key,_=service;report=s.adapter.load(key);report.delivery='ACKNOWLEDGED'
    report.telemetry=Telemetry(timestamp=datetime.now(timezone.utc),edge_status='DEGRADED',cloud_status='DISABLED',mode='LOCAL_ONLY',pending=0,cpu_percent=31,process_rss_mb=45)
    data,_,_,_=s.render(report);words=' '.join(text(data).split())
    for item in ('Telemetry at report generation time','ACKNOWLEDGED','physical siren actuation is not asserted','31.0%','45.00 MiB','LOCAL_ONLY'):assert item in words

def test_offline_lookup_render_write_and_api_download(service,monkeypatch):
    s,key,_=service
    from fastapi import FastAPI
    from Backend.incidents import api
    app=FastAPI();app.include_router(api.router)
    monkeypatch.setattr(api,'report_service',lambda:s)
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://local') as client:
            result=await client.post('/incidents/'+key+'/export')
            assert result.status_code==200 and result.headers['content-type']=='application/pdf'
            assert filename(key) in result.headers['content-disposition']
            assert result.headers['cache-control']=='no-store' and result.headers['x-report-version']=='qci5-report-v1'
            assert key in text(result.content)
            unknown=await client.post('/incidents/'+quality_id('test-source','missing')+'/export')
            assert unknown.status_code==404 and unknown.json()['detail']['error']=='NOT_FOUND'
            invalid=await client.post('/incidents/not-an-id/export')
            assert invalid.status_code==422
    # Windows event-loop construction uses an internal loopback socket pair.
    # Construct it before the all-network guard; the ASGI lookup/export path is guarded.
    with asyncio.Runner() as runner:
        runner.get_loop()
        with no_network() as audit:
            assert s.generate(key).status=='SUCCESS';runner.run(check());assert audit.attempts==0

def test_concurrent_exports_and_no_partial_files(service):
    s,key,root=service
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(lambda _:s.generate(key),range(12)))
    assert all(r.status=='SUCCESS' for r in results)
    assert key in text(Path(results[0].output_path).read_bytes())
    assert not list(root.rglob('.qci5-*.tmp'))

def test_failed_atomic_replace_preserves_valid_previous_pdf(service):
    s,key,root=service;first=s.generate(key);original=Path(first.output_path).read_bytes()
    with patch('QCI_5_Incident_PDF.service.os.replace',side_effect=OSError('simulated')):
        assert s.generate(key).status=='FAILED'
    assert Path(first.output_path).read_bytes()==original
    assert not list(root.rglob('.qci5-*.tmp'))

def test_cli_real_existing_store_and_unknown_record(service):
    s,key,root=service
    args=[sys.executable,'Backend/scripts/export_incident_pdf.py','--quality-database',str(s.adapter.database),'--output',str(root/'cli')]
    run=subprocess.run(args+['--incident-id',key],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
    assert run.returncode==0,run.stderr
    assert key in text(Path(json.loads(run.stdout)['output_path']).read_bytes())
    run=subprocess.run(args+['--incident-id',quality_id('test-source','unknown')],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
    assert run.returncode==1 and json.loads(run.stdout)['error']=='NOT_FOUND'

def test_evidence_manifest_must_match_current_stored_event_digest(service):
    s,key,root=service;path=root/'index.json'
    path.write_text(json.dumps({key:{'event_digest':'bad','evidence':[]}}))
    s.config.evidence_index=str(path)
    assert any('stale provenance' in w for w in s.adapter.load(key).warnings)

def test_existing_ultralytics_install_on_corruption_hook_is_bypassed(service):
    import ultralytics.utils.patches as patches
    s,key,root=service;path=root/'broken.png';path.write_bytes(b'invalid')
    report=s.adapter.load(key);report.evidence=[Evidence(role='Evidence image',path=str(path))]
    with patch('ultralytics.utils.checks.check_requirements',side_effect=AssertionError('Runtime installation forbidden')),no_network() as audit:
        data,warnings,_,_=s.render(report)
        assert 'Evidence image unavailable' in text(data) and audit.attempts==0

def test_quality_list_cache_identity_changes_after_delivery_ack(service):
    s,key,_=service;before=s.adapter.list_quality()[0]['updated_at']
    with closing(s.adapter.connect()) as db:
        status=json.loads(db.execute('SELECT status FROM qci3_events').fetchone()[0])
    import sqlite3
    with closing(sqlite3.connect(s.adapter.database)) as db,db:
        status['delivery']='ACKNOWLEDGED';db.execute('UPDATE qci3_events SET status=?',(json.dumps(status),))
    assert s.adapter.list_quality()[0]['updated_at']!=before

def test_quality_export_survives_unavailable_optional_legacy_store(service,monkeypatch):
    from fastapi import HTTPException
    from Backend.incidents import api
    s,key,_=service
    def unavailable():raise HTTPException(503,'Legacy store unavailable')
    monkeypatch.setattr(api,'repository',unavailable)
    monkeypatch.setattr(api,'configuration',lambda:s.config)
    assert api.report_service().generate(key).status=='SUCCESS'

def test_invalid_stored_required_fields_fail_without_publishing(service):
    import sqlite3
    s,key,root=service
    with closing(sqlite3.connect(s.adapter.database)) as db,db:
        status=json.loads(db.execute('SELECT status FROM qci3_events').fetchone()[0])
        status['confidence']=1.5
        db.execute('UPDATE qci3_events SET status=?',(json.dumps(status),))
    assert s.generate(key).error=='INVALID_INPUT' and not list(root.rglob('*.pdf'))

def test_long_source_identity_has_safe_windows_filename_and_full_pdf_id(service):
    s,_,_=service;key=quality_id('x'*128,'y'*128)
    assert identity(key)==['x'*128,'y'*128] and len(filename(key))<255
    report=s.adapter.load(quality_id('test-source','test-event'));report.incident_id=key
    data,_,_,_=s.render(report);assert key in text(data).replace('\n','')

@pytest.mark.parametrize('field,value',[('timestamp','2026-10-09T10:00:00'),('confidence',1.2),('confidence',float('nan')),('severity','extreme'),('defect_class','')])
def test_required_contract_values_rejected(service,field,value):
    s,key,_=service;data=s.adapter.load(key).model_dump();data[field]=value
    with pytest.raises(ValueError):ReportData.model_validate(data)
