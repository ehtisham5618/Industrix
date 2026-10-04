"""Optional real GPU benchmark; no training, 10-minute continuous-idle shutdown."""
from pathlib import Path
import modal

ROOT = Path(__file__).resolve().parents[1]
app = modal.App('industirx-cme-opt3')
volume = modal.Volume.from_name('industirx-cme-opt3', create_if_missing=True)
tracking_volume = modal.Volume.from_name('industirx-cme-opt2')
image = (modal.Image.debian_slim(python_version='3.11')
    .apt_install('libgl1','libglib2.0-0','ffmpeg')
    .pip_install('ultralytics==8.4.24','torch==2.10.0','torchvision==0.25.0','lap==0.5.13','mlflow==2.22.2','opencv-python==4.13.0.92'))
for name in ('CME_OPT3_ByteTrack','Confidence_Calibration','SED_1_Multi_Camera','SED_2_Alert_Escalation','Experiment_Tracking','Backend'):
    image = image.add_local_dir(ROOT/name, remote_path=f'/opt/project/{name}',
        ignore=lambda p:any(part in {'runtime','reports','outputs','benchmark','mlruns','__pycache__','execution_sources'} for part in p.parts)
                        or p.suffix.lower() in {'.pt','.mp4','.webm','.ogv'})
image = image.add_local_file(ROOT/'CME_OPT2_Model_Fine_Tuning/gpu_idle_watchdog.py',
    remote_path='/opt/project/CME_OPT2_Model_Fine_Tuning/gpu_idle_watchdog.py')


@app.function(image=image, volumes={'/work':volume}, timeout=1800)
def preflight(source_hashes):
    import hashlib
    import shutil
    result = {}
    for name, expected in source_hashes.items():
        with (Path('/opt/project')/name).open('rb') as f:
            assert hashlib.file_digest(f,'sha256').hexdigest() == expected, f'Execution source mismatch: {name}'
    for name in ('factory.ogv','best.pt','events.csv'):
        path = Path('/work')/name
        assert path.stat().st_size > 0
        with path.open('rb') as f: result[name] = hashlib.file_digest(f,'sha256').hexdigest()
    import cv2
    capture = cv2.VideoCapture('/work/factory.ogv')
    ok, frame = capture.read()
    print('CPU decoder preflight:',cv2.__version__,ok,frame.shape if ok else None,flush=True)
    capture.release()
    # Decode Theora with the system codec and retain a documented 600s MP4
    # derivative. Both comparison paths consume identical derivative bytes.
    import subprocess
    mp4 = Path('/work/factory.mp4')
    if not mp4.exists():
        subprocess.run(['ffmpeg','-v','error','-y','-i','/work/factory.ogv','-t','600',
            '-c:v','libx264','-crf','18','-preset','veryfast','-an',str(mp4)],check=True)
    capture = cv2.VideoCapture(str(mp4))
    ok, frame = capture.read()
    print('CPU MP4 decoder preflight:',ok,frame.shape if ok else None,flush=True)
    capture.release()
    assert ok, 'MP4 decoding must pass before allocating a GPU'
    del result['factory.ogv']
    with mp4.open('rb') as f: result['factory.mp4'] = hashlib.file_digest(f,'sha256').hexdigest()
    volume.commit()
    print('CPU input preflight:',result,flush=True)
    return result


@app.function(image=image,gpu='A10G',cpu=4,memory=16384,region='us-east',timeout=1800,
              volumes={'/work':volume,'/tracking':tracking_volume},scaledown_window=600,min_containers=0)
def benchmark(hashes):
    import hashlib
    import shutil
    import subprocess
    import sys
    import threading
    sys.path.insert(0,'/opt/project')
    from CME_OPT2_Model_Fine_Tuning.gpu_idle_watchdog import watch
    output = Path('/work/reports')
    output.mkdir(exist_ok=True)
    import json
    process = subprocess.Popen([sys.executable,'-u','-m','CME_OPT3_ByteTrack.gpu_worker',json.dumps(hashes)],
        cwd='/opt/project',stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    stop = threading.Event()
    threading.Thread(target=watch,args=(process,stop),daemon=True).start()
    try:
        with (output/'benchmark_terminal.txt').open('w') as stream:
            for line in process.stdout:
                print(line,end='',flush=True)
                stream.write(line); stream.flush()
        result = process.wait()
        stop.set()
        if result: raise RuntimeError(f'Benchmark process exited {result}; inspect actual logs')
        return 'industirx-cme-opt3:/reports/benchmark_summary.json'
    finally:
        volume.commit()
        tracking_volume.commit()


@app.local_entrypoint()
def main():
    import hashlib
    names = ('CME_OPT3_ByteTrack/benchmark.py','CME_OPT3_ByteTrack/pipeline.py',
             'CME_OPT3_ByteTrack/gpu_worker.py','SED_2_Alert_Escalation/scripts/escalation_state.py')
    hashes = {}
    for name in names:
        with (ROOT/name).open('rb') as f: hashes[name] = hashlib.file_digest(f,'sha256').hexdigest()
    print(benchmark.remote(preflight.remote(hashes)))
