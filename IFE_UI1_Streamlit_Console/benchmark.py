"""Real headless Edge + Streamlit + FastAPI + existing INT8 three-camera run.

Usage: python -m IFE_UI1_Streamlit_Console.benchmark --duration 180
Starts and cleans up only owned local processes. No mocked frames in this run.
"""
from __future__ import annotations
import argparse
import faulthandler
import csv
import json
import os
import platform
import signal
import subprocess
import sys
import time
from datetime import datetime,timezone
from pathlib import Path
import psutil
import requests
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
BACKEND='http://127.0.0.1:8000'

def wait_http(url,process,seconds=90):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        if process.poll() is not None:raise RuntimeError('Local server exited; inspect runtime logs')
        try:
            if requests.get(url,timeout=2).ok:return
        except requests.RequestException:pass
        time.sleep(.5)
    raise TimeoutError('Local server did not start')

def summary(values):
    import numpy as np
    if not values:return dict(count=0,mean=None,p50=None,p95=None,max=None)
    return dict(count=len(values),mean=float(np.mean(values)),p50=float(np.percentile(values,50)),
                p95=float(np.percentile(values,95)),max=float(max(values)),min=float(min(values)))

def stop_process(process):
    if process is None or process.poll() is not None:return
    try:process.send_signal(signal.CTRL_BREAK_EVENT);process.wait(timeout=15)
    except (OSError,subprocess.TimeoutExpired):
        for child in psutil.Process(process.pid).children(recursive=True):
            try:child.terminate()
            except psutil.Error:pass
        process.terminate();process.wait(timeout=10)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--duration',type=float,default=180)
    parser.add_argument('--smoke',action='store_true');args=parser.parse_args()
    out=ROOT/('IFE_UI1_Streamlit_Console/runtime/smoke' if args.smoke else 'Frontend/reports');out.mkdir(parents=True,exist_ok=True)
    runtime=ROOT/'IFE_UI1_Streamlit_Console/runtime';runtime.mkdir(exist_ok=True)
    backend=frontend=None;logs=[]
    env=os.environ.copy();env.update(INFERENCE_ENGINE='openvino',DEPLOYMENT_MODE='local',RUNTIME_EXTERNAL_SERVICES='',PYTHONUNBUFFERED='1')
    for port in (8000,8501):
        if any(c.status=='LISTEN' and c.laddr.port==port for c in psutil.net_connections('tcp')):
            raise RuntimeError(f'Port {port} already in use; refusing to touch an existing service')
    started=datetime.now(timezone.utc).isoformat()
    trace=(runtime/'benchmark_stack.log').open('w');logs.append(trace)
    faulthandler.dump_traceback_later(90,repeat=True,file=trace)
    try:
        def launch(command,name):
            log=(runtime/(name+'.log')).open('w',encoding='utf-8');logs.append(log)
            return subprocess.Popen(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,
                                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP|subprocess.CREATE_NO_WINDOW)
        backend=launch([sys.executable,'-m','uvicorn','Backend.main:api_app','--host','127.0.0.1','--port','8000'],'backend')
        frontend=launch([r'C:\Python314\python.exe','-m','streamlit','run','Frontend/app.py','--server.port','8501'],'streamlit')
        wait_http(BACKEND+'/system/status',backend);wait_http('http://127.0.0.1:8501/_stcore/health',frontend)
        response=requests.post(BACKEND+'/streams/start',params=dict(streams=3,engine='openvino',device='cpu',imgsz=640,persist_frames=15),timeout=90)
        response.raise_for_status();engine=response.json()['engine'];assert engine['name']=='OpenVINO' and engine['precision']=='INT8'
        # Short same-host baseline, before a browser subscribes. Not a CPU capacity test.
        baseline=[]
        for _ in range(15):
            time.sleep(1);baseline.append(requests.get(BACKEND+'/system/status',timeout=5).json()['telemetry'])
        print('Verified engine; baseline complete. Opening fresh Edge context.',flush=True)
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='msedge',headless=True)
            context=browser.new_context(viewport={'width':1600,'height':1100},device_scale_factor=1)
            page=context.new_page();errors=[];external=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.on('request',lambda r:external.append(r.url) if not r.url.startswith(('http://127.0.0.1:','ws://127.0.0.1:','data:','blob:')) else None)
            page.goto('http://127.0.0.1:8501/',wait_until='domcontentloaded',timeout=60000)
            deadline=time.monotonic()+60;frame=None
            while time.monotonic()<deadline:
                frame=next((f for f in page.frames if 'industrial_live_console/index.html' in f.url),None)
                if frame and frame.evaluate("!!window.__console && Object.keys(window.__console.metrics.counts).length===3"):break
                page.wait_for_timeout(500)
            else:raise RuntimeError('Three genuine live component canvases did not update')
            frame.wait_for_function('window.__console.metrics.telemetryUpdates>=3',timeout=15000)
            page.screenshot(path=str(out/'ife_ui1_desktop.png'),full_page=True)
            print('Three feeds rendered. Beginning measured run.',flush=True)
            frame.evaluate('window.__console.resetMetrics()')
            before=time.monotonic();backend_start=requests.get(BACKEND+'/cameras',timeout=5).json()
            frontend_process=psutil.Process(frontend.pid);frontend_process.cpu_percent(None)
            browser_samples=[];snapshots=[];last_progress=0
            while time.monotonic()-before<args.duration:
                page.wait_for_timeout(1000)
                elapsed=time.monotonic()-before
                browser_samples.append(dict(elapsed_seconds=elapsed,frontend_cpu_raw_percent=frontend_process.cpu_percent(None),
                    frontend_rss_mib=frontend_process.memory_info().rss/(1024*1024)))
                if elapsed-last_progress>=30:
                    snap=frame.evaluate('({counts:window.__console.metrics.counts,states:[...document.querySelectorAll(".camera .badge")].map(e=>e.textContent),telemetryUpdates:window.__console.metrics.telemetryUpdates})')
                    snapshots.append(dict(elapsed_seconds=elapsed,**snap));last_progress=elapsed
                    print(json.dumps(snap),flush=True)
            actual=time.monotonic()-before
            measured=frame.evaluate('JSON.parse(JSON.stringify(window.__console.metrics))')
            page.screenshot(path=str(out/'ife_ui1_live_detection.png'),full_page=True)
            backend_end=requests.get(BACKEND+'/cameras',timeout=5).json()
            desktop_layout=frame.evaluate('({overflow:document.documentElement.scrollWidth>innerWidth,canvases:[...document.querySelectorAll("canvas")].map(e=>({width:e.width,height:e.height})),engine:document.getElementById("engine").textContent,privacy:document.getElementById("privacy").textContent})')
            page.set_viewport_size({'width':750,'height':1050});page.wait_for_timeout(1200)
            page.screenshot(path=str(out/'ife_ui1_tablet.png'),full_page=True)
            tablet_layout=frame.evaluate('({overflow:document.documentElement.scrollWidth>innerWidth,columns:getComputedStyle(document.getElementById("cameras")).gridTemplateColumns})')
            page.set_viewport_size({'width':390,'height':3000});page.wait_for_timeout(1200)
            page.screenshot(path=str(out/'ife_ui1_mobile.png'),full_page=True)
            frame.locator('.console').screenshot(path=str(out/'ife_ui1_mobile_console.png'),timeout=15000)
            mobile_layout=frame.evaluate('({overflow:document.documentElement.scrollWidth>innerWidth,columns:getComputedStyle(document.getElementById("cameras")).gridTemplateColumns})')
            page.set_viewport_size({'width':1600,'height':1100});page.wait_for_timeout(500)
            # Real single-camera transport outage. The backend remains genuine;
            # no altered boxes/frames or synthetic inference is introduced.
            pre_fault=frame.evaluate('JSON.parse(JSON.stringify(window.__console.metrics.counts))')
            frame.evaluate("[...document.querySelectorAll('.camera')].find(e=>e.dataset.camera==='camera_02').dataset.faultTest='transport isolation'")
            # Route only reconnects; force closure of the current socket using
            # test access explicitly exposed by this harness through CDP offline
            # is avoided. Server stream stop instead exercises actual stop below.
            # Block one transport using Playwright's websocket route on a fresh
            # page, then verify other genuine camera channels continue.
            print('Checking one camera transport failure.',flush=True)
            isolation=context.new_page();isolation_errors=[]
            # An intentionally silent camera_02 transport. No production frame
            # or detector output is synthesized; other sockets reach FastAPI.
            isolation.route_web_socket('**/cameras/camera_02/live',lambda ws:None)
            print('Transport route registered.',flush=True)
            isolation.goto('http://127.0.0.1:8501/',wait_until='domcontentloaded',timeout=60000)
            print('Isolation page loaded.',flush=True)
            isolation.wait_for_timeout(8000)
            isolated=next(f for f in isolation.frames if 'industrial_live_console/index.html' in f.url)
            fault=isolated.evaluate('({counts:window.__console.metrics.counts,states:[...document.querySelectorAll(".camera .badge")].map(e=>e.textContent)})')
            isolation.screenshot(path=str(out/'ife_ui1_camera_offline.png'),full_page=True);isolation.close()
            fault['kind']='Intentionally silent browser camera_02 transport; actual backend still runs all cameras'
            fault['pass']=fault['counts'].get('camera_01',0)>0 and fault['counts'].get('camera_03',0)>0 and fault['counts'].get('camera_02',0)==0
            # Existing Streamlit controls must remain clickable while frames run.
            print('Checking Streamlit stop control.',flush=True)
            control_before=time.monotonic()
            page.get_by_role('button',name='Stop feeds',exact=True).click()
            try:page.get_by_text('Streams stopped.',exact=True).wait_for(timeout=45000)
            except Exception:
                page.screenshot(path=str(runtime/'control_timeout.png'),full_page=True)
                print('Control failure alerts: '+str(page.locator('[data-testid="stAlert"]').all_text_contents()),flush=True)
                raise
            control_seconds=time.monotonic()-control_before
            page.wait_for_timeout(1500)
            frame=next(f for f in page.frames if 'industrial_live_console/index.html' in f.url)
            stopped_state=frame.evaluate('({engine:document.getElementById("engine").textContent,states:[...document.querySelectorAll(".camera .badge")].map(e=>e.textContent)})')
            page.screenshot(path=str(out/'ife_ui1_streams_stopped.png'),full_page=True)
            # Kill only owned backend after orderly stream stop, verifying genuine
            # backend-unavailable state rather than mocked telemetry.
            print('Checking backend outage.',flush=True)
            stop_process(backend);page.wait_for_timeout(5500)
            offline=frame.evaluate('({backend:document.getElementById("connection").textContent,engine:document.getElementById("engine").textContent,privacy:document.getElementById("privacy").textContent,states:[...document.querySelectorAll(".camera .badge")].map(e=>e.textContent)})')
            page.screenshot(path=str(out/'ife_ui1_backend_offline.png'),full_page=True)
            # Reconnect to an actually restarted backend, then exercise the
            # existing Streamlit start button rather than an injected frame.
            backend=launch([sys.executable,'-m','uvicorn','Backend.main:api_app','--host','127.0.0.1','--port','8000'],'backend_restarted')
            wait_http(BACKEND+'/system/status',backend)
            page.get_by_role('button',name='Start three feeds',exact=True).click()
            page.get_by_text('Three feeds started using the verified OpenVINO INT8 CPU artifact.',exact=True).wait_for(timeout=45000)
            frame=next(f for f in page.frames if 'industrial_live_console/index.html' in f.url)
            frame.wait_for_function("[...document.querySelectorAll('.camera .badge')].filter(e=>e.textContent==='LIVE').length===3",timeout=30000)
            reconnect=frame.evaluate('({engine:document.getElementById("engine").textContent,states:[...document.querySelectorAll(".camera .badge")].map(e=>e.textContent)})')
            page.screenshot(path=str(out/'ife_ui1_reconnected.png'),full_page=True)
            # Preserve image-upload UI and navigation responsiveness.
            page.get_by_role('tab',name='Image Inference').click()
            upload_preserved=page.get_by_text('Upload a textile/fabric image to detect and visualize fabric defects.',exact=True).is_visible()
            browser.close()
            samples=measured['samples'];telemetry=measured['telemetry'];latency=summary([s['delivery_ms'] for s in samples])
        fps={k:v/actual for k,v in measured['counts'].items()}
        report=dict(task='IFE-UI1',config_version='IFEUI1-multistream-console-v1',experiment_type='frontend_integration',
            started_at_utc=started,finished_at_utc=datetime.now(timezone.utc).isoformat(),status='completed',
            duration_requested_seconds=args.duration,duration_actual_seconds=actual,
            hardware=dict(platform=platform.platform(),cpu=platform.processor(),logical_cpus=psutil.cpu_count()),
            browser='Fresh headless Microsoft Edge via Playwright; no existing profile or authenticated session',
            versions=dict(python_backend=sys.version.split()[0],python_frontend='3.14.3',streamlit='1.63.0',playwright='1.58.0'),
            engine=engine,model_version='cme-opt2-focal-cosine-12class-v1',
            measurement=dict(start='Backend DetectionResult.result_ready_at after calibration/tracking/SED-2',
                end='Browser timestamp immediately after JPEG decode and canvas drawImage + overlays',
                includes='Notification, bounded latest-only transport, JPEG encoding, WebSocket transfer, browser decoding and canvas update',
                excluded='Earlier capture/sampling/inference; subsequent display paint/scan-out is not measured',
                clock='Browser performance.timeOrigin + performance.now aligned to backend epoch using lowest-RTT midpoint',
                clock_offset_ms=measured['clockOffsetMs'],clock_uncertainty_ms=measured['clockUncertaintyMs']),
            delivery_latency_ms=latency,inference_pipeline_ms=summary([s['inference_ms'] for s in samples]),
            capture_to_canvas_ms=summary([s['capture_to_canvas_ms'] for s in samples]),
            encoding_ms=summary([s['encoding_ms'] for s in samples]),transport_ms=summary([s['transport_ms'] for s in samples]),
            per_camera_update_fps=fps,aggregate_ui_update_fps=sum(fps.values()),
            telemetry=dict(updates=measured['telemetryUpdates'],system_cpu_percent=summary([s['cpu_system_percent'] for s in telemetry if s['cpu_system_percent'] is not None]),
                backend_rss_mib=summary([s['process_rss_mb'] for s in telemetry if s['process_rss_mb'] is not None]),
                backend_evaluated_fps=summary([s['aggregate_evaluated_fps'] for s in telemetry]),
                frontend_cpu_raw_percent=summary([s['frontend_cpu_raw_percent'] for s in browser_samples]),
                frontend_rss_mib=summary([s['frontend_rss_mib'] for s in browser_samples])),
            baseline_without_browser=dict(seconds=15,system_cpu_percent=summary([s['cpu_system_percent'] for s in baseline]),
                evaluated_fps=summary([s['aggregate_evaluated_fps'] for s in baseline]),
                limitation='Short sequential observational comparison, not an isolated causal CPU overhead test'),
            reliability=dict(browser_errors=errors,component_errors=measured['errors'],network_errors=measured['networkErrors'],
                external_browser_requests=sorted(set(external)),out_of_order=measured['outOfOrder'],stale_events=measured['staleEvents'],
                camera_states=measured['cameraEvents'],detected_frames=measured['detectedFrames'],
                confirmation_states=measured['confirmationStates'],backend_track_ids=measured['trackIds']),
            backend_start=backend_start,backend_end=backend_end,progress_snapshots=snapshots,
            layout=dict(desktop=desktop_layout,tablet=tablet_layout,mobile=mobile_layout),
            failure_tests=dict(single_camera_transport=fault,stop_control=dict(seconds=control_seconds,state=stopped_state),backend_offline=offline,reconnected=reconnect),
            image_upload_navigation_preserved=upload_preserved)
        acceptance={
            'real_three_feed_180_seconds':actual>=180 and len(fps)==3 and all(v>0 for v in fps.values()),
            'mean_delivery_below_50ms':latency['mean'] is not None and latency['mean']<50,
            'p95_delivery_below_50ms':latency['p95'] is not None and latency['p95']<50,
            'genuine_focus_detection_overlays':bool(measured['detectedFrames']),
            'independent_camera_failure':fault['pass'],
            'backend_offline_no_live_claim':offline['backend']=='Backend offline' and all(s!='LIVE' for s in offline['states']) and offline['privacy']=='Unavailable',
            'responsive_without_horizontal_overflow':not any(d['overflow'] for d in report['layout'].values()),
            'no_browser_or_component_errors':not errors and not measured['errors'],
            'truthful_local_engine_and_privacy':desktop_layout['engine']=='OpenVINO INT8 (CPU)' and desktop_layout['privacy']=='0% \u00b7 On-Premise' and not external,
            'image_upload_preserved':upload_preserved,
            'actual_backend_reconnection':len(reconnect['states'])==3 and all(s=='LIVE' for s in reconnect['states'])}
        report['acceptance']=acceptance;report['overall']='PASS' if all(acceptance.values()) else 'FAIL'
        (out/'ife_ui1_metrics.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        for name,rows in [('ife_ui1_latency_samples.csv',samples),('ife_ui1_telemetry_samples.csv',browser_samples)]:
            if rows:
                with (out/name).open('w',newline='',encoding='utf-8') as stream:
                    writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        print(json.dumps(dict(status=report['status'],overall=report['overall'],duration=actual,delivery_ms=latency,
                             fps=fps,acceptance=acceptance),indent=2),flush=True)
    finally:
        if backend and backend.poll() is None:
            try:requests.post(BACKEND+'/streams/stop',timeout=40)
            except requests.RequestException:pass
        stop_process(backend);stop_process(frontend)
        faulthandler.cancel_dump_traceback_later()
        for log in logs:log.close()

if __name__=='__main__':main()
