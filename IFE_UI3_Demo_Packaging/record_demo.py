"""Record actual Edge UI; real native sources, inference, policy, storage/export."""
import argparse
import csv
import io
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
import psutil
from pypdf import PdfReader
from playwright.sync_api import sync_playwright
from ESE_CPU1_Quantization.common import ROOT,digest
from IFE_UI1_Streamlit_Console.benchmark import stop_process,wait_http,summary

TASK=ROOT/'IFE_UI3_Demo_Packaging';URL='http://127.0.0.1:8000'

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--seconds',type=float,default=125);args=parser.parse_args()
    runtime=TASK/'runtime'/('recording_'+datetime.now().strftime('%Y%m%d_%H%M%S'));runtime.mkdir(parents=True)
    env=os.environ.copy();env.update(INFERENCE_ENGINE='openvino',DEPLOYMENT_MODE='local',RUNTIME_EXTERNAL_SERVICES='',IFE_UI3_DEMO='true',
        PYTHONUNBUFFERED='1',INCIDENT_DATABASE=str(runtime/'events.db'),INCIDENT_SNAPSHOTS=str(runtime/'snapshots'),
        INCIDENT_UI_TIMINGS_PATH=str(runtime/'ui_export_timings.jsonl'),DEMO_NETWORK_JOURNAL=str(runtime/'external_network.jsonl'))
    for port in (8000,8501):
        import socket
        with socket.socket() as sock:sock.bind(('127.0.0.1',port))
    backend=frontend=None;files=[];external=[];errors=[];trace=[];timeline=[];samples=[];export_data=None
    def launch(command,name):
        log=(runtime/(name+'.log')).open('w',encoding='utf-8');files.append(log)
        return subprocess.Popen(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP|subprocess.CREATE_NO_WINDOW)
    def get(path):
        r=requests.get(URL+path,timeout=10);r.raise_for_status();return r.json()
    def start():
        r=requests.post(URL+'/streams/start',params=dict(engine='openvino',device='cpu',streams=3,persist_frames=15),timeout=90);r.raise_for_status()
        assert r.json()['engine']['name']=='OpenVINO';return r.json()
    def stop():requests.post(URL+'/streams/stop',timeout=40).raise_for_status()
    began_utc=datetime.now(timezone.utc).isoformat()
    try:
        # First real run verifies the exact footage and fresh export, then restarts
        # the application using the SAME local DB before the official recording.
        env['CAMERA_CONFIG']=str(TASK/'configs/rehearsal.json')
        backend=launch([sys.executable,'-X','utf8','-m','IFE_UI3_Demo_Packaging.offline_server'],'rehearsal_backend')
        wait_http(URL+'/system/status',backend);start()
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            rows=get('/incidents')['incidents']
            fire=next((row for row in rows if row['class_name']=='fire' and row['camera_id']=='camera_02' and row['severity']=='critical'),None)
            if fire:break
            time.sleep(1)
        else:raise RuntimeError('Real detector did not confirm and escalate the rehearsal hazard')
        old_id=fire['incident_id'];pre=requests.post(URL+'/incidents/'+old_id+'/export',timeout=10);pre.raise_for_status()
        assert len(PdfReader(io.BytesIO(pre.content)).pages)>=2
        rehearsal=dict(incident=fire,generation_ms=float(pre.headers['X-PDF-Generation-Ms']))
        stop();stop_process(backend)
        env['CAMERA_CONFIG']=str(TASK/'configs/demo.json')
        backend=launch([sys.executable,'-X','utf8','-m','IFE_UI3_Demo_Packaging.offline_server'],'recording_backend')
        frontend=launch([r'C:\Python314\python.exe','-X','utf8','-m','IFE_UI3_Demo_Packaging.offline_server','--frontend'],'streamlit')
        wait_http(URL+'/system/status',backend);wait_http('http://127.0.0.1:8501/_stcore/health',frontend)
        persisted=get('/incidents/'+old_id);assert persisted['snapshot_sha256']==rehearsal['incident']['snapshot_sha256']
        restarted=requests.post(URL+'/incidents/'+old_id+'/export',timeout=10);restarted.raise_for_status()
        assert len(PdfReader(io.BytesIO(restarted.content)).pages)>=2
        restart=dict(persisted_incident_id=old_id,pdf_generation_ms=float(restarted.headers['X-PDF-Generation-Ms']),model_offline_reload=True)
        engine=start();source_started=time.monotonic()
        # Warmed pre-demo operational benchmark. No capacity-FPS claim.
        time.sleep(5);before=get('/cameras');benchmark=[];bench_start=time.monotonic()
        for _ in range(20):
            time.sleep(1);benchmark.append(get('/system/status')['telemetry'])
        after=get('/cameras');bench_seconds=time.monotonic()-bench_start
        preflight=dict(seconds=bench_seconds,samples=benchmark,counts_before=before,counts_after=after)
        print('Genuine incident/PDF and offline restart verified; warm benchmark complete.',flush=True)
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='msedge',headless=True)
            context=browser.new_context(viewport=dict(width=1920,height=1080),device_scale_factor=1,accept_downloads=True,
                record_video_dir=str(runtime/'browser_video'),record_video_size=dict(width=1920,height=1080))
            def guard(route):
                if urlparse(route.request.url).hostname not in ('127.0.0.1','localhost','::1'):
                    external.append(route.request.url);route.abort()
                else:route.continue_()
            context.route('**/*',guard)
            page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
            page.add_init_script("window.__incidentClicks=[];addEventListener('click',e=>{const b=e.target.closest('button');if(b&&b.textContent.trim()==='Export Incident PDF')window.__incidentClicks.push(Date.now()/1000);},true);")
            page.goto('http://127.0.0.1:8501',wait_until='domcontentloaded',timeout=60000)
            page.get_by_role('button',name='Start three feeds',exact=True).wait_for(timeout=45000)
            deadline=time.monotonic()+45;component=None
            while time.monotonic()<deadline:
                component=next((f for f in page.frames if 'industrial_live_console/index.html' in f.url),None)
                if component and component.evaluate('!!window.__console && Object.keys(window.__console.metrics.counts).length===3'):break
                page.wait_for_timeout(500)
            else:
                page.screenshot(path=str(runtime/'startup_failure.png'))
                raise RuntimeError('Three actual live browser canvases did not become ready')
            component.wait_for_function("document.getElementById('engine').textContent==='OpenVINO INT8 (CPU)'",timeout=15000)
            component.evaluate('window.__console.resetMetrics()')
            video=page.video;record_start=time.monotonic();events_done=set();new_id=None
            page.screenshot(path=str(ROOT/'reports/ife_ui3_three_feeds.png'))
            while time.monotonic()-record_start<args.seconds:
                elapsed=time.monotonic()-record_start
                status=get('/system/status');samples.append(dict(elapsed_seconds=elapsed,**status['telemetry']))
                actual=get('/cameras/camera_02/latest');ds=actual.get('detections',[])
                if actual.get('frame_id')!= (trace[-1].get('frame_id') if trace else None):
                    trace.append(dict(elapsed_seconds=elapsed,**actual))
                rows=get('/incidents')['incidents'];new=next((r for r in rows if r['incident_id']!=old_id and r['class_name']=='fire' and r['camera_id']=='camera_02'),None)
                if new:new_id=new['incident_id']
                # Mouse movement highlights real controls; no injected metrics/UI.
                if elapsed>12 and 'feeds' not in events_done:
                    component.locator('.console').scroll_into_view_if_needed()
                    page.screenshot(path=str(ROOT/'reports/ife_ui3_three_feeds.png'))
                    events_done.add('feeds');timeline.append(dict(at=elapsed,action='Scroll actual console to show all three complete feeds and telemetry'))
                if elapsed>35 and 'telemetry' not in events_done:
                    component.locator('#latency').hover();events_done.add('telemetry');timeline.append(dict(at=elapsed,action='Highlight actual rolling inference mean/P95 and live hardware telemetry'))
                if new and new['severity']=='critical' and 'critical' not in events_done:
                    component.locator('.severity.critical').wait_for(timeout=15000)
                    component.get_by_text('SIMULATED SAFETY SHUTDOWN',exact=False).wait_for(timeout=15000)
                    component.locator('.console').scroll_into_view_if_needed()
                    timeline.append(dict(at=elapsed,action='Real 15-observation fire incident escalated to critical',incident_id=new_id))
                    page.screenshot(path=str(ROOT/'reports/ife_ui3_confirmed_hazard.png'));events_done.add('critical')
                if elapsed>92 and new and new['severity']=='critical' and 'history' not in events_done:
                    page.get_by_role('button',name='Refresh incident history',exact=True).click()
                    page.wait_for_timeout(900)
                    page.get_by_text('Incident History',exact=True).scroll_into_view_if_needed()
                    combo=page.get_by_role('combobox')
                    if combo.input_value()!=new_id:
                        combo.fill(new_id);combo.press('ArrowDown');combo.press('Enter')
                    assert combo.input_value()==new_id
                    page.get_by_text('Evidence snapshot',exact=True).click();page.wait_for_timeout(700)
                    page.screenshot(path=str(ROOT/'reports/ife_ui3_incident.png'))
                    timeline.append(dict(at=elapsed,action='Refresh newly generated incident and expand native cropped evidence',incident_id=new_id));events_done.add('history')
                if elapsed>107 and new and new['severity']=='critical' and 'export' not in events_done:
                    page.get_by_role('button',name='Export Incident PDF',exact=True).click()
                    download=page.get_by_role('button',name='Download Incident PDF',exact=True);download.wait_for(timeout=15000)
                    with page.expect_download(timeout=15000) as pending:download.click()
                    saved=runtime/'downloaded_incident.pdf';pending.value.save_as(saved)
                    parsed=PdfReader(saved);text='\n'.join(pg.extract_text() for pg in parsed.pages)
                    assert new_id in text and 'CRITICAL' in text and 'SAMPLE / DEMONSTRATION' in text
                    entries=[json.loads(l) for l in (runtime/'ui_export_timings.jsonl').read_text().splitlines()]
                    clicks=page.evaluate('window.__incidentClicks')
                    export_data=dict(filename=pending.value.suggested_filename,pages=len(parsed.pages),sha256=digest(saved),
                        click_to_bytes_seconds=entries[-1]['bytes_ready_at']-clicks[-1],**entries[-1])
                    assert export_data['click_to_bytes_seconds']<2
                    page.screenshot(path=str(ROOT/'reports/ife_ui3_pdf_export.png'))
                    timeline.append(dict(at=time.monotonic()-record_start,action='Actual fresh ReportLab export and Streamlit PDF download',incident_id=new_id));events_done.add('export')
                if int(elapsed)//30>len([t for t in timeline if t['action']=='progress']):
                    print('Recording '+str(round(elapsed))+'s; incident='+str(new_id),flush=True);timeline.append(dict(at=elapsed,action='progress'))
                page.wait_for_timeout(650)
            measured=component.evaluate('JSON.parse(JSON.stringify(window.__console.metrics))')
            recorded_seconds=time.monotonic()-record_start
            end=get('/cameras');final=get('/incidents/'+new_id) if new_id else None;iot=get('/iot/status')
            assert iot['state']=='SHUTDOWN_TRIGGERED'
            assert export_data and new_id and new_id!=old_id
            assert set(measured['counts'])=={'camera_01','camera_02','camera_03'} and measured['confirmationStates'].get('candidate',0)>0
            assert measured['confirmationStates'].get('confirmed',0)+measured['confirmationStates'].get('active',0)>0
            assert not errors and not external
            context.close();webm=Path(video.path());browser.close()
        stop()
    finally:
        if backend and backend.poll() is None:
            try:requests.post(URL+'/streams/stop',timeout=40)
            except requests.RequestException:pass
        stop_process(frontend);stop_process(backend)
        for file in files:file.close()
    attempts=(runtime/'external_network.jsonl').read_text().splitlines() if (runtime/'external_network.jsonl').exists() else []
    assert not attempts
    target=TASK/'runtime/Atlantis_Sprint4_CPU_Ready_Demo_v0.4.0.mp4'
    # Trim only pre-readiness loading seconds. The recorded application frames
    # remain untouched: no static overlays, retiming or synthetic animation.
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(webm)],text=True))
    total=float(probe['format']['duration']);offset=max(0,total-recorded_seconds)
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-ss',str(offset),'-i',str(webm),'-t',str(args.seconds),
        '-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p','-movflags','+faststart','-an',str(target)],check=True)
    info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(target)],text=True));stream=info['streams'][0]
    assert 105<=float(info['format']['duration'])<=135 and (stream['width'],stream['height'])==(1920,1080)
    subprocess.run(['ffmpeg','-v','error','-i',str(target),'-f','null','-'],check=True)
    for second in (10,40,75,100,115):
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-ss',str(second),'-i',str(target),'-frames:v','1',str(runtime/f'video_{second}.png')],check=True)
    import fitz
    doc=fitz.open(runtime/'downloaded_incident.pdf')
    for number in range(len(doc)):doc[number].get_pixmap(matrix=fitz.Matrix(1.25,1.25)).save(runtime/f'pdf_page_{number+1}.png')
    data=dict(task='IFE-UI3',version='IFEUI3-local-demo-v1',started_at_utc=began_utc,finished_at_utc=datetime.now(timezone.utc).isoformat(),
        runtime=str(runtime.relative_to(ROOT)),status='completed',engine=engine,rehearsal=rehearsal,restart=restart,preflight=preflight,
        recording=dict(path=str(target.relative_to(ROOT)),duration_seconds=float(info['format']['duration']),width=stream['width'],height=stream['height'],
            codec=stream['codec_name'],fps=stream['r_frame_rate'],bytes=target.stat().st_size,sha256=digest(target),source_webm=str(webm.relative_to(ROOT)),
            loading_trim_seconds=offset,audio='Silent walkthrough; no narration',decoded_entire_video=True,upload='MANUAL ACTION REQUIRED',share_url=None),
        measured_seconds=recorded_seconds,timeline=timeline,incident=final,pdf_export=export_data,final_cameras=end,iot=iot,
        browser_metrics=measured,telemetry=samples,performance=dict(inference_mean_ms=summary([s['model_inference_mean_ms'] for s in samples if 'model_inference_mean_ms' in s]),
            inference_p95_ms=summary([s['model_inference_p95_ms'] for s in samples if 'model_inference_p95_ms' in s]),
            operational_evaluated_fps=summary([s['aggregate_evaluated_fps'] for s in samples]),ui_delivery_ms=summary([s['delivery_ms'] for s in measured['samples']]),
            system_cpu_percent=summary([s['cpu_system_percent'] for s in samples]),backend_rss_mib=summary([s['process_rss_mb'] for s in samples]),
            aggregate_canvas_updates_fps=sum(measured['counts'].values())/recorded_seconds,engine_capacity_fps=None),
        offline=dict(method='Both backend and frontend reject non-loopback Python TCP connect/connect_ex; fresh Edge blocks non-loopback HTTP. All configured OpenCV sources are local files.',
            physical_wifi_disconnected=False,external_internet_disabled_for_entire_os=False,external_tcp_attempts=attempts,browser_external_requests=external,
            cloud_inference_calls=0,external_storage_calls=0,external_alert_calls=0,remote_pdf_calls=0),errors=errors,
        hardware=dict(os=platform.platform(),cpu=platform.processor(),logical_cpus=psutil.cpu_count()),pr_created=False,merged=False,release_tag_created=False)
    (ROOT/'reports/ife_ui3_demo_metrics.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
    with (runtime/'result_trace.jsonl').open('w',encoding='utf-8') as output:
        for item in trace:output.write(json.dumps(item)+'\n')
    print(json.dumps(dict(recording=data['recording'],performance=data['performance'],incident_id=new_id,pdf_export=export_data),indent=2),flush=True)

if __name__=='__main__':main()
