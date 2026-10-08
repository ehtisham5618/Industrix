"""Launch existing backend/frontend on loopback; Ctrl+C cleans up owned children."""
import os
import subprocess
import sys
import time
from .prepare import ROOT,TASK,CONFIG
from IFE_UI1_Streamlit_Console.benchmark import stop_process,wait_http

def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--config',default=str(CONFIG));parser.add_argument('--database',default=str(TASK/'runtime/demo/events.db'))
    args=parser.parse_args();db=__import__('pathlib').Path(args.database).resolve();db.parent.mkdir(parents=True,exist_ok=True)
    for port in (8000,8501):
        import socket
        with socket.socket() as check:check.bind(('127.0.0.1',port))
    env=os.environ.copy();env.update(CAMERA_CONFIG=str(args.config),INCIDENT_DATABASE=str(db),INCIDENT_SNAPSHOTS=str(db.parent/'snapshots'),
        INFERENCE_ENGINE='openvino',DEPLOYMENT_MODE='local',RUNTIME_EXTERNAL_SERVICES='',IFE_UI3_DEMO='true',PYTHONUNBUFFERED='1',
        DEMO_NETWORK_JOURNAL=str(db.parent/'external_network.jsonl'))
    processes=[]
    try:
        for interpreter,extra in [(sys.executable,[]),(r'C:\Python314\python.exe',['--frontend'])]:
            processes.append(subprocess.Popen([interpreter,'-m','IFE_UI3_Demo_Packaging.offline_server',*extra],cwd=ROOT,env=env,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP|subprocess.CREATE_NO_WINDOW))
        wait_http('http://127.0.0.1:8000/system/status',processes[0]);wait_http('http://127.0.0.1:8501/_stcore/health',processes[1])
        print('Open http://127.0.0.1:8501 and click Start three feeds. Ctrl+C stops owned servers.',flush=True)
        while all(p.poll() is None for p in processes):time.sleep(1)
        raise RuntimeError('A server exited unexpectedly')
    except KeyboardInterrupt:pass
    finally:
        for process in reversed(processes):stop_process(process)

if __name__=='__main__':main()
