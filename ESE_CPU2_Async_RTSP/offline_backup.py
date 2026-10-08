"""Create and actually restore-verify the two local task commits."""
import json
import subprocess
import zipfile
import hashlib

from .benchmark import ROOT,digest,write_json

BRANCH='feature/atlantis-async-rtsp'
BASE='f239c770dfdaea862b4e108f3dacd3abc8c72484'


def main():
    backup=ROOT/'ESE_CPU2_Async_RTSP/backups';backup.mkdir(parents=True,exist_ok=True)
    commits=subprocess.check_output(['git','log','--format=%H%x09%s',f'{BASE}..{BRANCH}'],cwd=ROOT,text=True).splitlines()
    if len(commits)!=2: raise RuntimeError('Delivery requires exactly two new task commits')
    bundle=backup/'ESE_CPU2_complete_history.bundle'
    subprocess.run(['git','bundle','create',str(bundle),'--all'],cwd=ROOT,check=True)
    check=subprocess.run(['git','bundle','verify',str(bundle)],cwd=ROOT,check=True,text=True,
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    (backup/'bundle_verification.txt').write_text(check.stdout,encoding='utf-8')
    head=subprocess.check_output(['git','rev-parse',BRANCH],cwd=ROOT,text=True).strip()
    probe=ROOT/'ESE_CPU2_Async_RTSP/runtime'/('restore_probe_'+head[:7])
    if not probe.exists():
        subprocess.run(['git','clone','--quiet','--branch',BRANCH,str(bundle),str(probe)],check=True)
    restored=subprocess.check_output(['git','-C',str(probe),'rev-parse','HEAD'],text=True).strip()
    if restored!=head: raise RuntimeError('Restored HEAD does not match saved branch')
    inputs=[ROOT/'Backend/best.pt',ROOT/'data/test_factory_clip.mp4',
        ROOT/'Confidence_Calibration/benchmark/media/chemical_hazard_01_hazmat_training.webm',
        ROOT/'Confidence_Calibration/benchmark/media/no_helmet_01_workers_roof.webm']
    inputs += [p for p in (ROOT/'Experiment_Tracking/mlruns').rglob('*') if p.is_file()]
    archive=backup/'ESE_CPU2_local_runtime.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as stream:
        for path in inputs: stream.write(path,path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(archive) as stream:
        if stream.testzip() is not None: raise RuntimeError('Runtime ZIP CRC failure')
        for path in inputs:
            with stream.open(path.relative_to(ROOT).as_posix()) as item:
                if hashlib.file_digest(item,'sha256').hexdigest()!=digest(path):
                    raise RuntimeError('Archived input hash mismatch')
    record=dict(branch=BRANCH,base_commit=BASE,commits=commits,
        bundle=dict(path=bundle.relative_to(ROOT).as_posix(),sha256=digest(bundle),verified=True,
            clone_restore_verified=True,restored_head=restored),
        runtime_archive=dict(path=archive.relative_to(ROOT).as_posix(),sha256=digest(archive),
            files_verified=len(inputs),contents='Source checkpoint, three public videos and local MLflow state; no credentials'),
        remote=subprocess.check_output(['git','remote','get-url','origin'],cwd=ROOT,text=True).strip(),
        sync_command=f'git push -u origin {BRANCH}',pushed=False,pr_created=False)
    write_json(backup/'delivery_manifest.json',record)
    print(json.dumps(record,indent=2))


if __name__=='__main__': main()
