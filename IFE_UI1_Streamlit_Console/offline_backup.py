"""Verified bundle and runtime recovery without organization repository access."""
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path
from ESE_CPU1_Quantization.common import digest

ROOT=Path(__file__).resolve().parents[1]
BRANCH='feature/atlantis-streamlit-ui'
BASE='d071e197c6c69835cf11109a7c5a357339c69234'

def main():
    backup=ROOT/'IFE_UI1_Streamlit_Console/backups';backup.mkdir(parents=True,exist_ok=True)
    commits=subprocess.check_output(['git','log','--format=%H%x09%s',BASE+'..'+BRANCH],cwd=ROOT,text=True).splitlines()
    if len(commits)!=2:raise RuntimeError('Exactly two UI1 task commits required')
    report=json.loads((ROOT/'Frontend/reports/ife_ui1_metrics.json').read_text())
    if report['status']!='completed' or report['duration_actual_seconds']<180:
        raise RuntimeError('Final delivery requires the actual completed three-minute integration run')
    bundle=backup/'IFE_UI1_complete_history.bundle'
    subprocess.run(['git','bundle','create',str(bundle),'--all'],cwd=ROOT,check=True)
    check=subprocess.run(['git','bundle','verify',str(bundle)],cwd=ROOT,check=True,text=True,
                         stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    (backup/'bundle_verification.txt').write_text(check.stdout,encoding='utf-8')
    head=subprocess.check_output(['git','rev-parse',BRANCH],cwd=ROOT,text=True).strip()
    probe=ROOT/'IFE_UI1_Streamlit_Console/runtime'/('restore_probe_'+head[:7])
    if not probe.exists():subprocess.run(['git','clone','--quiet','--branch',BRANCH,str(bundle),str(probe)],check=True)
    restored=subprocess.check_output(['git','-C',str(probe),'rev-parse','HEAD'],text=True).strip()
    if restored!=head:raise RuntimeError('Bundle recovery HEAD mismatch')
    inputs=[ROOT/'Backend/best.pt',*[ROOT/'Backend/weights/openvino_int8'/n for n in ('model.xml','model.bin','metadata.yaml')],
        ROOT/'data/test_factory_clip.mp4',ROOT/'Confidence_Calibration/benchmark/media/chemical_hazard_01_hazmat_training.webm',
        ROOT/'Confidence_Calibration/benchmark/media/no_helmet_01_workers_roof.webm']
    inputs += [p for p in (ROOT/'Experiment_Tracking/mlruns').rglob('*') if p.is_file()]
    archive=backup/'IFE_UI1_local_runtime.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as stream:
        for path in inputs:stream.write(path,path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(archive) as stream:
        if stream.testzip() is not None:raise RuntimeError('Archive CRC validation failed')
        for path in inputs:
            with stream.open(path.relative_to(ROOT).as_posix()) as item:
                if hashlib.file_digest(item,'sha256').hexdigest()!=digest(path):raise RuntimeError('Archive bytes differ')
    result=dict(branch=BRANCH,base_commit=BASE,commits=commits,
        bundle=dict(path=bundle.relative_to(ROOT).as_posix(),sha256=digest(bundle),verified=True,
                    clone_restore_verified=True,restored_head=restored),
        runtime_archive=dict(path=archive.relative_to(ROOT).as_posix(),sha256=digest(archive),files_verified=len(inputs)),
        measured_status=report['status'],acceptance=report['overall'],duration_seconds=report['duration_actual_seconds'],
        pushed=False,pr_created=False,remote=subprocess.check_output(['git','remote','get-url','origin'],cwd=ROOT,text=True).strip(),
        sync_command='git push -u origin '+BRANCH)
    (backup/'delivery_manifest.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
