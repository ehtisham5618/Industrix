"""Real existing QCI-3 research event export, socket-guarded download and RSS proof."""
import argparse
import asyncio
from contextlib import closing
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import shutil
import sqlite3
import statistics
import subprocess
import sys
import threading
import time
import psutil
from pypdf import PdfReader
from .adapter import Adapter,ROOT,quality_id
from .contracts import Config,Telemetry
from .service import PDFService
from QCI_1_Surface_Defect_Segmentation.offline import no_network

TASK=ROOT/'QCI_5_Incident_PDF';REPORTS=ROOT/'reports/qci5'
def write(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def digest(path):
    with Path(path).open('rb') as handle:return hashlib.file_digest(handle,'sha256').hexdigest()
def execution_sources():
    return dict(commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        modules={str(p.relative_to(ROOT)).replace('\\','/'):digest(p) for p in sorted(TASK.glob('*.py'))})
def summary(values):
    rows=sorted(values);return dict(count=len(rows),mean_ms=statistics.mean(rows),p50_ms=statistics.median(rows),p95_ms=rows[min(len(rows)-1,int(.95*len(rows)))],max_ms=max(rows))

def sample_configuration():
    """Bind existing inference evidence to its exact stored Event digest, never by basename."""
    from QCI_3_Severity_IoT.contracts import Event,Status
    runtime=TASK/'runtime';runtime.mkdir(parents=True,exist_ok=True)
    prior=json.loads((ROOT/'reports/qci3/loopback_demo.json').read_text())
    database=ROOT/prior['audit_database'];source='demo.critical';event_id='actual-2';key=quality_id(source,event_id)
    with closing(sqlite3.connect(database)) as db:
        stored=db.execute('SELECT status,digest FROM qci3_events WHERE source=? AND event=?',(source,event_id)).fetchone()
    if stored is None:raise RuntimeError('Existing QCI-3 sample record unavailable')
    status=Status.model_validate_json(stored[0])
    predictions=json.loads((ROOT/'QCI_3_Severity_IoT/runtime/fresh_predictions.json').read_text())
    prediction=next(p for p in predictions if p['prediction']['predicted_class_name']==status.class_name)
    original=Event(source_id=source,event_id=event_id,sequence=0,observed_at=status.first_seen,prediction=prediction['prediction'])
    if hashlib.sha256(original.model_dump_json().encode()).hexdigest()!=stored[1]:raise RuntimeError('Original Event digest does not bind these classifier/evidence results')
    records=[json.loads(line) for line in (ROOT/'reports/qci1/segmentation/samples.jsonl').read_text().splitlines()]
    record=next(r for r in records if r['sample_id']==prediction['source_sample_id'])
    image=ROOT/'QCI_1_Surface_Defect_Segmentation/runtime/segmentation_dataset'/record['image']['path']
    overlay=Path(prediction['prediction']['heatmap']['overlay_path'])
    evidence=[]
    for role,path in (('Evidence image',image),('Model Attribution Heatmap',overlay)):
        evidence.append(dict(role=role,path=path.relative_to(ROOT).as_posix(),sha256=digest(path),
            context='Existing QCI-3 research-demo inference; source sample '+record['sample_id']+'. Acquisition timestamp unavailable. '+
                ('Grad-CAM overlay, target class defect; attribution is not a ground-truth defect mask.' if role.startswith('Model') else 'Original curated KolektorSDD image; noncommercial research/evaluation. ')+
                ' KolektorSDD: ViCoS, University of Ljubljana; Tabernik et al. (2019), DOI 10.1007/s10845-019-01476-x. CC BY-NC-SA 4.0. https://www.vicos.si/resources/kolektorsdd/'))
    index=runtime/'sample_evidence.json';write(index,{key:dict(event_digest=stored[1],is_sample=True,evidence=evidence)})
    config=Config(quality_database=database.relative_to(ROOT).as_posix(),evidence_index=index.relative_to(ROOT).as_posix(),output_dir='QCI_5_Incident_PDF/runtime/exports')
    write(runtime/'sample_config.json',config.model_dump(mode='json'))
    write(runtime/'sample_lineage.json',dict(incident_id=key,database=config.quality_database,event_digest=stored[1],
        source_sample_id=record['sample_id'],evidence=evidence,original_event_digest_verified=True,
        model_version=status.model_version,policy_version=status.policy_version,severity=status.severity.value,state=status.state.value,
        delivery=status.delivery.value,confidence=status.confidence,model_sha256=json.loads((ROOT/'reports/qci2/model_artifact.json').read_text())['sha256']))
    return config,key

def telemetry(config):
    from QCI_4_Edge_Telemetry.api import EdgeService
    from QCI_4_Edge_Telemetry.contracts import Config as EdgeConfig
    edge=EdgeService(EdgeConfig(database='QCI_5_Incident_PDF/runtime/telemetry.db',alerts_database=config.quality_database))
    try:
        edge.collector.sample();time.sleep(.05);snapshot=edge.collector.sample()
        write(REPORTS/'report_time_telemetry.json',snapshot.model_dump(mode='json'))
        return Telemetry(timestamp=snapshot.timestamp,edge_status=snapshot.edge_status.value,cloud_status=snapshot.cloud.status.value,
            mode=snapshot.cloud.mode.value,pending=snapshot.spool.pending,cpu_percent=snapshot.resources.cpu_percent,process_rss_mb=snapshot.resources.process_rss_mb)
    finally:edge.stop()

async def api_export(service,key):
    import httpx
    from fastapi import FastAPI
    from unittest.mock import patch
    from Backend.incidents import api
    app=FastAPI();app.include_router(api.router)
    with patch.object(api,'report_service',return_value=service):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://local') as client:
            response=await client.post('/incidents/'+key+'/export')
            assert response.status_code==200 and response.headers['content-type']=='application/pdf'
            assert response.content.startswith(b'%PDF-')
            return dict(status=response.status_code,content_type=response.headers['content-type'],filename=response.headers['content-disposition'],
                report_version=response.headers['x-report-version'],pdf_bytes=len(response.content),network='In-process existing FastAPI route under all-socket-connect prohibition')

def demo():
    REPORTS.mkdir(parents=True,exist_ok=True)
    sources=execution_sources()
    config,key=sample_configuration()
    with no_network() as audit:
        t=telemetry(config);service=PDFService(Adapter(config=config,telemetry=lambda:t))
        result=service.generate(key)
        if result.status!='SUCCESS':raise RuntimeError(result.model_dump_json())
        target=REPORTS/'sample_incident_report.pdf';shutil.copyfile(result.output_path,target)
        pdf=PdfReader(target);words='\n'.join(p.extract_text() for p in pdf.pages)
        for token in (key,'CRITICAL','RESOLVED','ACKNOWLEDGED','defect','74.9%','Model Attribution Heatmap','Telemetry at report generation time','SAMPLE / DEMONSTRATION'):
            assert token in words,token
        assert sum(len(p.images) for p in pdf.pages)==2
        network_attempts=audit.attempts
    with asyncio.Runner() as runner:
        runner.get_loop()
        with no_network() as audit:api=runner.run(api_export(service,key));assert audit.attempts==0
    import os
    env={**os.environ,'QCI5_CONFIG':str(TASK/'runtime/sample_config.json')}
    code='from QCI_1_Surface_Defect_Segmentation.offline import no_network\nfrom Backend.scripts.export_incident_pdf import main\nwith no_network() as audit:\n result=main()\n assert audit.attempts==0\nraise SystemExit(result)'
    cli=subprocess.run([sys.executable,'-X','utf8','-c',code,'--incident-id',key],cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',timeout=30)
    (REPORTS/'pdf_export_demo_output.txt').write_text(cli.stdout+cli.stderr,encoding='utf-8')
    assert cli.returncode==0,cli.stderr
    # Service sample contains report-time telemetry; cold CLI intentionally records
    # unavailable telemetry when it has no running monitor in its process.
    result=dict(sample_export=result.model_dump(mode='json'),incident_id=key,sample_pdf='reports/qci5/sample_incident_report.pdf',
        sample_sha256=digest(target),pages=len(pdf.pages),embedded_images=2,offline_socket_attempts=network_attempts,
        api=api,cli=json.loads(cli.stdout),lineage=json.loads((TASK/'runtime/sample_lineage.json').read_text()),
        generated_at=datetime.now(timezone.utc).isoformat(),execution_sources=sources)
    write(REPORTS/'pdf_demo.json',result);print(json.dumps(result));return result

def profile():
    sources=execution_sources()
    config,key=sample_configuration();service=PDFService(Adapter(config=config))
    process=psutil.Process();samples=[];phase=['warmup'];stop=threading.Event();latencies=[]
    def sample():
        while not stop.is_set():samples.append((time.monotonic(),phase[0],process.memory_info().rss/2**20));stop.wait(.05)
    thread=threading.Thread(target=sample,name='qci5-rss');start=process.memory_info().rss/2**20
    handles_start=process.num_handles() if hasattr(process,'num_handles') else None;thread.start()
    try:
        with no_network() as audit:
            for i in range(500):
                phase[0]='warmup' if i<50 else 'first' if i<275 else 'second'
                result=service.generate(key)
                if result.status!='SUCCESS':raise RuntimeError(result.model_dump_json())
                if i>=50:latencies.append(result.model_dump(mode='json'))
            assert audit.attempts==0
    finally:stop.set();thread.join()
    end=process.memory_info().rss/2**20
    first=[r[2] for r in samples if r[1]=='first'];second=[r[2] for r in samples if r[1]=='second']
    if len(first)<2 or len(second)<2:raise RuntimeError('Missing stable profile windows')
    drift=abs(statistics.mean(second)-statistics.mean(first))/statistics.mean(first)*100
    result=dict(exports=500,warmup=50,exports_per_window=225,sampling_hz=20,
        start_rss_mib=start,peak_rss_mib=max(r[2] for r in samples),end_rss_mib=end,
        first_mean_rss_mib=statistics.mean(first),second_mean_rss_mib=statistics.mean(second),matched_window_drift_percent=drift,
        raw_endpoint_change_percent=(end-start)/start*100,strict_less_than_5_percent_pass=drift<5,
        handles_start=handles_start,handles_end=process.num_handles() if hasattr(process,'num_handles') else None,
        sampler_stopped=not thread.is_alive(),offline_socket_attempts=0,
        methodology='Continuous 20 Hz process RSS; 50 warmup exports then two equal 225-export windows; same stored incident, two real images, no inference or PDF-byte cache.',
        timings={name:summary([r[name] for r in latencies]) for name in ('latency_ms','lookup_ms','evidence_ms','render_ms','write_ms')},
        partial_files=len(list((TASK/'runtime/exports').glob('.qci5-*.tmp'))),final_files=len(list((TASK/'runtime/exports').glob('*.pdf'))),execution_sources=sources)
    with (REPORTS/'memory_samples.csv').open('w',encoding='utf-8',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(['monotonic_seconds','phase','rss_mib']);writer.writerows(samples)
    write(REPORTS/'memory_profile.json',result);print(json.dumps(result))
    if drift>=5:raise RuntimeError('Genuine strict memory gate failed')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['demo','profile']);args=parser.parse_args()
    demo() if args.mode=='demo' else profile()
if __name__=='__main__':main()
