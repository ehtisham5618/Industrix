"""Read actual local dependencies, model, sources and storage permissions."""
import importlib
import json
import socket
import subprocess
import tempfile
from pathlib import Path
from Backend.offline_policy import configure_local_runtime
configure_local_runtime()
from .prepare import ROOT,TASK,CONFIG
from .offline_server import install_guard

def main():
    checks={}
    for name in ('openvino','cv2','torch','fastapi','uvicorn','reportlab','pypdf','playwright','lap','pytest'):
        try:module=importlib.import_module(name);checks[name]=dict(pass_=True,version=getattr(module,'__version__',None))
        except ImportError as exc:checks[name]=dict(pass_=False,error=str(exc))
    frontend=subprocess.run([r'C:\Python314\python.exe','-c','import streamlit; print(streamlit.__version__)'],capture_output=True,text=True)
    checks['frontend']=dict(pass_=frontend.returncode==0,version=frontend.stdout.strip())
    for name in ('ffmpeg','ffprobe'):
        run=subprocess.run([name,'-version'],capture_output=True,text=True);checks[name]=dict(pass_=run.returncode==0,version=run.stdout.splitlines()[0])
    connect=socket.socket.connect;connect_ex=socket.socket.connect_ex
    try:
        install_guard()
        from ESE_CPU3_Soak_Test.engine import OpenVINODetector
        detector=OpenVINODetector();checks['selected_model']=dict(pass_=True,verification=detector.verification);detector.close()
    finally:socket.socket.connect=connect;socket.socket.connect_ex=connect_ex
    from SED_1_Multi_Camera.scripts.config import load_camera_configs
    from SED_1_Multi_Camera.scripts.camera_source import FileCameraSource
    sources=[]
    for camera in load_camera_configs(CONFIG):
        source=FileCameraSource(camera.source,loop=False,realtime=False)
        try:source.open();ok,frame=source.read();sources.append(dict(camera=camera.camera_id,pass_=bool(ok and frame.size),source=str(Path(camera.source).relative_to(ROOT))))
        finally:source.close()
    checks['three_sources']=dict(pass_=len(sources)==3 and all(s['pass_'] for s in sources),sources=sources)
    runtime=TASK/'runtime';runtime.mkdir(parents=True,exist_ok=True)
    from Backend.incidents.repository import IncidentRepository
    with tempfile.TemporaryDirectory(prefix='readiness_',dir=runtime) as name:
        repo=IncidentRepository(Path(name)/'events.db',Path(name)/'snapshots')
        with repo.connect() as db:assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        repo.snapshots.mkdir();(repo.snapshots/'write_probe.txt').write_text('local',encoding='utf-8')
        checks['sqlite_and_snapshots']=dict(pass_=True)
    with tempfile.TemporaryFile(dir=ROOT/'reports') as probe:probe.write(b'reports writable')
    checks['reports_writable']=dict(pass_=True)
    for port in (8000,8501):
        try:
            with socket.socket() as sock:sock.bind(('127.0.0.1',port))
            checks['port_'+str(port)]=dict(pass_=True)
        except OSError as exc:checks['port_'+str(port)]=dict(pass_=False,error=str(exc))
    result=dict(checks=checks,overall='PASS' if all(c['pass_'] for c in checks.values()) else 'FAIL')
    (TASK/'reports/readiness.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    for key,value in checks.items():print(key,'PASS' if value['pass_'] else 'FAIL')
    if result['overall']!='PASS':raise SystemExit(1)

if __name__=='__main__':main()
