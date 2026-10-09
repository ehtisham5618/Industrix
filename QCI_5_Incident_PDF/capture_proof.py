"""Render actual PDFs and verify a fresh browser download through the existing UI."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlsplit
import urllib.request
from .adapter import ROOT
from .verify import REPORTS,TASK,write

def render():
    binary=next((TASK/'runtime/poppler').rglob('pdftoppm.exe'))
    result=subprocess.run([str(binary),'-r','100','-png',str(REPORTS/'sample_incident_report.pdf'),str(REPORTS/'sample_page')],capture_output=True,text=True)
    if result.returncode:raise RuntimeError(result.stderr)
    write(REPORTS/'pdf_render_proof.json',dict(renderer=str(binary.relative_to(ROOT)),
        pdf_sha256=hashlib.sha256((REPORTS/'sample_incident_report.pdf').read_bytes()).hexdigest(),
        pages=[dict(path=p.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(REPORTS.glob('sample_page-*.png'))]))

def browser():
    from playwright.sync_api import sync_playwright
    from pypdf import PdfReader
    key=json.loads((REPORTS/'pdf_demo.json').read_text())['incident_id']
    processes=[];logs=[];blocked=[]
    try:
        for name,args in [('api',['-m','QCI_5_Incident_PDF.demo_server']),
            ('ui',['-m','streamlit','run','QCI_5_Incident_PDF/demo_ui.py','--server.address','127.0.0.1','--server.port','8505','--server.headless','true','--browser.gatherUsageStats','false'])]:
            log=(REPORTS/('live_'+name+'_terminal.txt')).open('w',encoding='utf-8');logs.append(log)
            processes.append(subprocess.Popen([sys.executable,'-X','utf8',*args],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)))
        for port in (8765,8505):
            for attempt in range(100):
                try:
                    with urllib.request.urlopen('http://127.0.0.1:'+str(port)+('/incidents' if port==8765 else '/_stcore/health'),timeout=1) as response:
                        if response.status==200:break
                except OSError:time.sleep(.2)
            else:raise RuntimeError('Local preview did not start')
        with sync_playwright() as runtime:
            browser=runtime.chromium.launch(channel='msedge',headless=True,args=['--disable-background-networking','--disable-component-update'])
            try:
                context=browser.new_context(viewport={'width':1440,'height':1400},accept_downloads=True)
                def route(value):
                    u=urlsplit(value.request.url)
                    if u.scheme in ('data','blob','file') or u.hostname in ('127.0.0.1','localhost'):value.continue_()
                    else:blocked.append(value.request.url);value.abort()
                context.route('**/*',route)
                page=context.new_page();page.goto('http://127.0.0.1:8505',wait_until='load')
                page.get_by_role('combobox').wait_for(timeout=30000);page.get_by_role('combobox').click()
                page.get_by_role('combobox').fill(key)
                page.get_by_role('option',name=key,exact=True).click()
                page.get_by_role('button',name='Export Incident PDF',exact=True).click()
                download_control=page.get_by_role('button',name='Download Incident PDF',exact=True)
                download_control.wait_for(timeout=30000)
                download_control.scroll_into_view_if_needed()
                page.screenshot(path=str(REPORTS/'live_download_ui.png'),full_page=True)
                with page.expect_download(timeout=15000) as expected:download_control.click()
                download=expected.value;destination=TASK/'runtime/browser_download.pdf';download.save_as(destination)
                words='\n'.join(p.extract_text() for p in PdfReader(destination).pages)
                assert key in words and 'CRITICAL' in words and 'ACKNOWLEDGED' in words
                proof=dict(browser='Fresh headless Microsoft Edge, no existing profile/credentials',
                    surface='Live isolated Streamlit harness using Frontend.incidents.incident_history and existing FastAPI /incidents router; not a full inference console',
                    incident_id=key,download_filename=download.suggested_filename,download_bytes=destination.stat().st_size,
                    download_sha256=hashlib.sha256(destination.read_bytes()).hexdigest(),actual_download_verified=True,
                    external_page_requests_blocked=blocked,api_process_external_tcp_guard=True,
                    browser_skill_bootstrap='Failed before setup: kernel assets path not found (os error 3); fresh browser fallback',
                    screenshot='reports/qci5/live_download_ui.png')
                write(REPORTS/'ui_download_proof.json',proof);print(json.dumps(proof))
            finally:browser.close()
    finally:
        for process in reversed(processes):
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait()
        for log in logs:log.close()

if __name__=='__main__':render();browser()
