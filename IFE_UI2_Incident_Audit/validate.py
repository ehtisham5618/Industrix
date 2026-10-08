"""Explicit offline core/CLI benchmark and actual Streamlit PDF downloads."""
import csv
import hashlib
import io
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch
import psutil
import requests
from pypdf import PdfReader
from playwright.sync_api import sync_playwright
from Backend.incidents.repository import IncidentRepository,ROOT,utc
from Backend.incidents.pdf import export_pdf
from IFE_UI1_Streamlit_Console.benchmark import wait_http,stop_process,summary
from .sample import create_sample

def main():
    runtime=ROOT/'IFE_UI2_Incident_Audit/runtime';out=ROOT/'reports';out.mkdir(exist_ok=True)
    demo=runtime/'demo_v2';repo=IncidentRepository(demo/'events.db',demo/'snapshots',initialize=False)
    incident=repo.list()[0];incident_id=incident['incident_id'];rows=[]
    offline=runtime/('offline_'+str(time.time_ns()))
    # Dependency installation is outside this workflow. Logging, real tracking,
    # snapshot and export now run with all Python socket connections forbidden.
    with patch.object(socket.socket,'connect',side_effect=AssertionError('Network forbidden')) as direct,patch('socket.create_connection',side_effect=AssertionError('Network forbidden')) as helper:
        trace=create_sample(offline)
        offline_repo=IncidentRepository(offline/'events.db',offline/'snapshots',initialize=False)
        offline_pdf,_=export_pdf(offline_repo,trace['incident']['incident_id'])
        assert offline_pdf.startswith(b'%PDF-');assert direct.call_count==helper.call_count==0
        for number in range(20):
            data,elapsed=export_pdf(repo,incident_id);rows.append(dict(run=number+1,incident_id=incident_id,seconds=elapsed))
    command=[sys.executable,'-X','utf8','Backend/scripts/export_incident_pdf.py','--incident-id',incident_id,
        '--database',str(repo.database),'--snapshots',str(repo.snapshots),'--output','reports/']
    began=time.perf_counter();run=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
    cli_seconds=time.perf_counter()-began;assert run.returncode==0,run.stderr
    target=out/(incident_id+'_incident_report.pdf');target.replace(out/'sample_incident.pdf')
    (runtime/'cli_terminal.txt').write_text(run.stdout+'\nExit code: '+str(run.returncode),encoding='utf-8')
    invalid=subprocess.run([*command[:5],'INC-2026-999999',*command[6:]],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
    assert invalid.returncode!=0
    pdf=PdfReader(out/'sample_incident.pdf');text='\n'.join(page.extract_text() for page in pdf.pages)
    for value in (incident_id,'WARNING','SAMPLE / DEMONSTRATION','Signature','Corrective','not an official OSHA'):
        assert value in text,value
    assert sum(len(p.images) for p in pdf.pages)>0
    ui=[];backend=frontend=None;files=[]
    journal=runtime/'ui_timings.jsonl';journal.write_text('',encoding='utf-8')
    env=os.environ.copy();env.update(INCIDENT_DATABASE=str(repo.database),INCIDENT_SNAPSHOTS=str(repo.snapshots),
        RUNTIME_EXTERNAL_SERVICES='',DEPLOYMENT_MODE='local',PYTHONUNBUFFERED='1',YOLO_OFFLINE='true',YOLO_AUTOINSTALL='false',INCIDENT_UI_TIMINGS_PATH=str(journal))
    for port in (8000,8501):
        assert not any(c.status=='LISTEN' and c.laddr.port==port for c in psutil.net_connections('tcp')),f'Port {port} in use'
    external=[];errors=[]
    try:
        def launch(command,name):
            file=(runtime/(name+'.log')).open('w',encoding='utf-8');files.append(file)
            return subprocess.Popen(command,cwd=ROOT,env=env,stdout=file,stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP|subprocess.CREATE_NO_WINDOW)
        # The backend guard allows only loopback TCP connections, and logs any
        # attempted external connection. No cloud inference/report service runs.
        backend=launch([sys.executable,'-X','utf8','-m','IFE_UI2_Incident_Audit.offline_server'],'offline_backend')
        frontend=launch([r'C:\Python314\python.exe','-m','streamlit','run','Frontend/app.py','--server.port','8501'],'streamlit')
        wait_http('http://127.0.0.1:8000/system/status',backend);wait_http('http://127.0.0.1:8501/_stcore/health',frontend)
        # Exercise production source/engine wiring as a monitoring regression.
        response=requests.post('http://127.0.0.1:8000/streams/start',params={'engine':'openvino','device':'cpu','streams':3},timeout=90)
        response.raise_for_status()
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='msedge',headless=True)
            context=browser.new_context(viewport={'width':1600,'height':1750},accept_downloads=True)
            page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
            page.add_init_script("window.__incidentClicks=[];addEventListener('click',e=>{const b=e.target.closest('button');if(b&&b.textContent.trim()==='Export Incident PDF')window.__incidentClicks.push(Date.now()/1000);},true);")
            def guard(route):
                from urllib.parse import urlparse
                if urlparse(route.request.url).hostname not in ('127.0.0.1','localhost','::1'):
                    external.append(route.request.url);route.abort()
                else:route.continue_()
            context.route('**/*',guard)
            page.goto('http://127.0.0.1:8501/',wait_until='domcontentloaded',timeout=60000)
            try:page.get_by_role('button',name='Export Incident PDF',exact=True).wait_for(timeout=45000)
            except Exception:
                page.screenshot(path=str(runtime/'ui_failure.png'),full_page=True)
                print('UI failure: '+page.locator('body').inner_text()[:3000],flush=True)
                print('External page requests: '+str(external),flush=True)
                raise
            component=next(f for f in page.frames if 'industrial_live_console/index.html' in f.url)
            component.wait_for_function('Object.keys(window.__console.metrics.counts).length===3',timeout=45000)
            for n in range(5):
                began=time.perf_counter();page.get_by_role('button',name='Export Incident PDF',exact=True).click()
                download_button=page.get_by_role('button',name='Download Incident PDF',exact=True)
                download_button.wait_for(timeout=15000)
                page.get_by_text('Fresh PDF generation:',exact=False).wait_for(timeout=15000)
                text_metrics=page.get_by_text('Fresh PDF generation:',exact=False).inner_text()
                elapsed=time.perf_counter()-began
                click_epoch=page.evaluate('window.__incidentClicks.at(-1)')
                entries=[json.loads(line) for line in journal.read_text(encoding='utf-8').splitlines()]
                ready_epoch=entries[-1]['bytes_ready_at']
                action_seconds=ready_epoch-click_epoch
                assert action_seconds>=0
                with page.expect_download(timeout=15000) as pending:download_button.click()
                downloaded=pending.value;path=runtime/f'ui_download_{n+1}.pdf';downloaded.save_as(path)
                parsed=PdfReader(path);assert incident_id in ''.join(p.extract_text() for p in parsed.pages)
                ui.append(dict(run=n+1,actual_click_to_pdf_bytes_seconds=action_seconds,click_epoch=click_epoch,bytes_ready_epoch=ready_epoch,
                    button_to_download_control_seconds=elapsed,frontend_caption=text_metrics,
                    filename=downloaded.suggested_filename,bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
                # Remove the previous bytes-ready widget by a normal refresh;
                # selected incident remains the same and every export is fresh.
                page.get_by_role('button',name='Refresh incident history',exact=True).click();page.wait_for_timeout(500)
                page.get_by_role('button',name='Download Incident PDF',exact=True).wait_for(state='hidden',timeout=15000)
            page.get_by_role('button',name='Export Incident PDF',exact=True).click();page.wait_for_timeout(500)
            page.screenshot(path=str(out/'ife_ui2_ui_export.png'),full_page=True)
            live=component.evaluate('({counts:window.__console.metrics.counts,engine:document.getElementById("engine").textContent})')
            browser.close()
        requests.post('http://127.0.0.1:8000/streams/stop',timeout=40).raise_for_status()
    finally:
        if backend and backend.poll() is None:
            try:requests.post('http://127.0.0.1:8000/streams/stop',timeout=40)
            except requests.RequestException:pass
        stop_process(backend);stop_process(frontend)
        for file in files:file.close()
    guard_text=(runtime/'offline_backend.log').read_text(encoding='utf-8')
    assert 'EXTERNAL_NETWORK_BLOCKED' not in guard_text
    assert not external and not errors
    with repo.connect(readonly=True) as db:
        schema=[dict(column=r[1],type=r[2]) for r in db.execute('PRAGMA table_info(incidents)')]
        sqlite_version=db.execute('SELECT sqlite_version()').fetchone()[0]
        journal=db.execute('PRAGMA journal_mode').fetchone()[0]
    import re
    server_times=[float(re.search(r'Fresh PDF generation: ([\d.]+)',r['frontend_caption'])[1])/1000 for r in ui]
    frontend_times=[float(re.search(r'bytes ready: ([\d.]+)',r['frontend_caption'])[1])/1000 for r in ui]
    metrics=dict(task='IFE-UI2',version='IFEUI2-incident-audit-v1',status='completed',finished_at_utc=utc(),
        sample=incident,sample_trace=json.loads((demo/'sample_trace.json').read_text(encoding='utf-8')),
        database=dict(production_path='Backend/data/events.db',validation_path=str(repo.database.relative_to(ROOT)),
            sqlite_version=sqlite_version,journal_mode=journal,tables=['incidents','incident_sequence','incident_transitions'],schema=schema),
        fresh_pdf_seconds=summary([r['seconds'] for r in rows]),cli_process_seconds=cli_seconds,
        api_fresh_generation_seconds=summary(server_times),frontend_request_to_bytes_seconds=summary(frontend_times),
        browser_button_to_download_control_seconds=summary([r['button_to_download_control_seconds'] for r in ui]),
        actual_button_to_pdf_bytes_seconds=summary([r['actual_click_to_pdf_bytes_seconds'] for r in ui]),
        ui_exports=ui,live_monitor_regression=live,
        offline=dict(sqlite_write=True,snapshot_save=True,pdf_generation=True,streamlit_download=True,
            core_socket_connections_attempted=0,external_browser_requests=external,backend_external_attempts=0,
            method='All Python core sockets blocked; real backend forbids non-loopback TCP; browser blocks all non-loopback page HTTP requests. UI/API calls use only loopback.'),
        sample_pdf=dict(path='reports/sample_incident.pdf',pages=len(pdf.pages),bytes=(out/'sample_incident.pdf').stat().st_size,
            sha256=hashlib.sha256((out/'sample_incident.pdf').read_bytes()).hexdigest(),embedded_images=sum(len(p.images) for p in pdf.pages)),
        errors=errors)
    metrics['overall']='PASS' if max(metrics['fresh_pdf_seconds']['max'],metrics['api_fresh_generation_seconds']['max'],
        metrics['frontend_request_to_bytes_seconds']['max'],metrics['actual_button_to_pdf_bytes_seconds']['max'])<2 else 'FAIL'
    (out/'ife_ui2_metrics.json').write_text(json.dumps(metrics,indent=2),encoding='utf-8')
    with (out/'ife_ui2_pdf_export_samples.csv').open('w',newline='',encoding='utf-8') as file:
        writer=csv.DictWriter(file,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    print(json.dumps({k:metrics[k] for k in ('overall','fresh_pdf_seconds','frontend_request_to_bytes_seconds','browser_button_to_download_control_seconds')},indent=2),flush=True)

if __name__=='__main__':main()
