"""Preserve local Git history and ignored deployment artifacts without repository access."""
import argparse
import json
from pathlib import Path
import subprocess
import zipfile

from .common import ROOT,REPORTS,digest,write_json

BRANCH='feature/atlantis-openvino-quant'


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--artifacts-only',action='store_true')
    args=parser.parse_args()
    backup=ROOT/'ESE_CPU1_Quantization/backups'
    backup.mkdir(parents=True,exist_ok=True)
    archive=backup/'ESE_CPU1_deployment_artifacts.zip'
    inputs=[ROOT/'Backend/best.pt',ROOT/'Backend/weights/onnx_fp16/best_fp16.onnx',
        *[ROOT/'Backend/weights/openvino_int8'/name for name in ('model.xml','model.bin','metadata.yaml')]]
    if not archive.exists():
        with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as stream:
            for path in inputs:stream.write(path,path.relative_to(ROOT).as_posix())
    # Verify every archived byte against the current selected deployment files.
    import hashlib
    with zipfile.ZipFile(archive) as stream:
        assert stream.testzip() is None
        for path in inputs:
            with stream.open(path.relative_to(ROOT).as_posix()) as item:
                assert hashlib.file_digest(item,'sha256').hexdigest()==digest(path)
    artifact_record=dict(path=archive.relative_to(ROOT).as_posix(),bytes=archive.stat().st_size,
        sha256=digest(archive),verified=True,files={p.relative_to(ROOT).as_posix():digest(p) for p in inputs},
        contents='Source checkpoint and selected deployment models; no images or credentials')
    write_json(REPORTS/'artifact_backup.json',artifact_record)
    if args.artifacts_only:
        print('Deployment archive created and every file hash verified:',archive)
        return
    base=subprocess.check_output(['git','merge-base','HEAD','feature/atlantis-bytetrack-filter'],cwd=ROOT,text=True).strip()
    commits=subprocess.check_output(['git','log','--format=%H%x09%s',f'{base}..{BRANCH}'],cwd=ROOT,text=True).splitlines()
    assert len(commits)==2, 'Task delivery must contain exactly2 commits'
    bundle=backup/'ESE_CPU1_complete_history.bundle'
    subprocess.run(['git','bundle','create',str(bundle),'--all'],cwd=ROOT,check=True)
    result=subprocess.run(['git','bundle','verify',str(bundle)],cwd=ROOT,check=True,text=True,
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    (backup/'bundle_verification.txt').write_text(result.stdout,encoding='utf-8')
    head=subprocess.check_output(['git','rev-parse',BRANCH],cwd=ROOT,text=True).strip()
    probe=ROOT/'ESE_CPU1_Quantization/runtime'/('restore_probe_'+head[:7])
    if not probe.exists():
        subprocess.run(['git','clone','--quiet','--branch',BRANCH,str(bundle),str(probe)],check=True)
    restored=subprocess.check_output(['git','-C',str(probe),'rev-parse','HEAD'],text=True).strip()
    assert restored==head,'Bundle restore did not recover the saved task head'
    tracking=ROOT/'Experiment_Tracking/mlruns'
    tracking_archive=backup/'ESE_CPU1_local_mlflow.zip'
    if tracking.exists():
        with zipfile.ZipFile(tracking_archive,'w',compression=zipfile.ZIP_DEFLATED) as stream:
            for path in sorted(tracking.rglob('*')):
                if path.is_file():stream.write(path,path.relative_to(ROOT).as_posix())
        with zipfile.ZipFile(tracking_archive) as stream:assert stream.testzip() is None
    record=dict(branch=BRANCH,base_commit=base,commits=commits,
        bundle=dict(path=bundle.relative_to(ROOT).as_posix(),sha256=digest(bundle),bytes=bundle.stat().st_size,
            verified=True,restore_clone_verified=True,restored_head=restored),deployment_archive=artifact_record,
        local_mlflow_archive=dict(path=tracking_archive.relative_to(ROOT).as_posix(),sha256=digest(tracking_archive)) if tracking.exists() else None,
        push_status='Deferred: user reports organization repository access revoked',pr_created=False,
        sync_command=f'git push -u origin {BRANCH}',remote=subprocess.check_output(['git','remote','get-url','origin'],text=True).strip())
    write_json(backup/'delivery_manifest.json',record)
    print(json.dumps(record,indent=2))


if __name__=='__main__':main()
