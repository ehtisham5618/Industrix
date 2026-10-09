"""Verify two-commit Git history and independent local model/data recovery."""
from __future__ import annotations
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any
# Recovery packaging must not import Torch/OpenCV in its parent process: those
# imports add unnecessary RAM and can mutate Windows native DLL search settings
# inherited by the recovered-model subprocess.
ROOT=Path(__file__).resolve().parents[1]
TASK=ROOT/'QCI_2_Defect_Classifier'
REPORTS=ROOT/'reports/qci2'

BRANCH='feature/sprint2-qci2-defect-classifier'
BASE='d63ff417b363ea8fd81e0027f9ca458afdda4aee'


def file_hash(path: Path) -> str:
    """Stream a local artifact hash using only the standard library."""
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def git(args: list[str],cwd: Path=ROOT) -> str:
    """Run checked local Git operations, with no shell interpolation."""
    return subprocess.check_output(['git',*args],cwd=cwd,text=True,stderr=subprocess.STDOUT).strip()


def main() -> None:
    """Restore real weights, unchanged QCI-1 bytes and verify future local push."""
    if git(['status','--porcelain']):raise ValueError('Commit task deliverables before recovery verification')
    commits=git(['log','--format=%H%x09%s',BASE+'..'+BRANCH]).splitlines()
    if len(commits)!=2:raise ValueError('Exactly two new QCI-2 commits required')
    backup=TASK/'backups';backup.mkdir(parents=True,exist_ok=True)
    bundle=backup/'QCI_2_complete_history.bundle';git(['bundle','create',str(bundle),'--all'])
    (backup/'bundle_verification.txt').write_text(git(['bundle','verify',str(bundle)])+'\n',encoding='utf-8')
    head=git(['rev-parse',BRANCH]);probe=TASK/'runtime'/('restore_probe_'+head[:7])
    if probe.exists():raise ValueError('Existing restore probe preserved; use a fresh HEAD')
    git(['clone','--quiet','--branch',BRANCH,str(bundle),str(probe)])
    assert git(['rev-parse','HEAD'],probe)==head
    inputs=[TASK/'runtime/run_v1',TASK/'runtime/initialization',TASK/'runtime/execution_sources',
        ROOT/'QCI_1_Surface_Defect_Segmentation/runtime/segmentation_dataset',REPORTS]
    # Preserve byte-identical QCI-1 lineage even if Git checkout changes newline
    # conventions on a different Windows machine.
    files=[ROOT/'reports/qci1/segmentation/samples.jsonl',ROOT/'reports/qci1/segmentation/dataset_manifest.json']
    tracking=json.loads((REPORTS/'experiment_tracking.json').read_text(encoding='utf-8'))
    for run in (ROOT/'Experiment_Tracking/mlruns').glob('*/'+tracking['run_id']):
        inputs.append(run);files.append(run.parent/'meta.yaml')
    archive=backup/'QCI_2_local_model_and_runtime.zip';members:list[dict[str,Any]]=[]
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_STORED,allowZip64=True) as zipped:
        for directory in inputs:
            files.extend(p for p in directory.rglob('*') if p.is_file() and '__pycache__' not in p.parts)
        for path in files:
            name=path.relative_to(ROOT).as_posix();zipped.write(path,name)
            members.append(dict(path=name,bytes=path.stat().st_size,sha256=file_hash(path)))
    with zipfile.ZipFile(archive) as zipped:
        for member in members:
            with zipped.open(member['path']) as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==member['sha256']
            if member['path'].startswith(('QCI_2_Defect_Classifier/runtime/','QCI_1_Surface_Defect_Segmentation/runtime/','reports/qci1/segmentation/samples.jsonl','reports/qci1/segmentation/dataset_manifest.json')):
                zipped.extract(member['path'],probe)
    artifact=json.loads((REPORTS/'model_artifact.json').read_text(encoding='utf-8'))
    assert file_hash(probe/artifact['checkpoint'])==artifact['sha256']
    # This helper executes inside the RECOVERED clone; explicit dataset override
    # prevents accidentally reading the original repository's absolute paths.
    check=probe/'QCI_2_Defect_Classifier/runtime/restore_validation.py'
    check.write_text('''import json,sys
from pathlib import Path
root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root))
import cv2,numpy as np
# Initialize bounded native resize workers before Torch's CPU pools. This
# recovery probe validates numerical outputs, not a performance benchmark.
cv2.setNumThreads(1)
cv2.resize(np.zeros((2,2),dtype=np.float32),(3,3))
from QCI_2_Defect_Classifier.common import deterministic,load_config
from QCI_2_Defect_Classifier.data import ManifestDataset
from QCI_2_Defect_Classifier.infer import DefectClassifier
from QCI_1_Surface_Defect_Segmentation.offline import no_network
deterministic()
cfg=load_config(root/'QCI_2_Defect_Classifier/configs/qci2_reproduce.yaml')
data=ManifestDataset(cfg,'test');artifact=json.loads((root/'reports/qci2/model_artifact.json').read_text())
assert data.root == root/'QCI_1_Surface_Defect_Segmentation/runtime/segmentation_dataset'
expected=json.loads((root/'reports/qci2/test_predictions.json').read_text())
with no_network() as audit:
 service=DefectClassifier(root/artifact['checkpoint'],artifact['sha256'])
 for row,reference in zip(data.rows,expected):
  data[data.rows.index(row)]
  result=service.predict(dict(image=str(data.root/row.image.path)))
  assert result.status=='SUCCESS' and result.predicted_class_id==reference['prediction']['predicted_class_id']
  assert abs(result.confidence-reference['prediction']['confidence'])<1e-6
  assert result.heatmap is not None and not service.target_layer._forward_hooks
assert audit.attempts==0
print(json.dumps(dict(restored_samples=len(data),actual_model_and_cam_verified=True,original_data_used=False,dataset_root=str(data.root),network_attempts=audit.attempts)))
''',encoding='utf-8')
    restored=subprocess.run([sys.executable,'-X','utf8',str(check)],cwd=probe,text=True,capture_output=True,encoding='utf-8')
    (backup/'restored_inference_output.txt').write_text(restored.stdout+restored.stderr+'\nExit:'+str(restored.returncode),encoding='utf-8')
    assert restored.returncode==0,restored.stdout+restored.stderr
    bare=TASK/'runtime'/('sync_probe_'+head[:7]+'.git');git(['init','--quiet','--bare',str(bare)])
    git(['remote','set-url','origin',str(bare)],probe)
    sync=subprocess.run(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(probe/'QCI_2_Defect_Classifier/sync_when_access_returns.ps1')],text=True,capture_output=True)
    assert sync.returncode==0 and git(['--git-dir',str(bare),'rev-parse',BRANCH])==head
    (backup/'local_sync_verification.txt').write_text(sync.stdout+sync.stderr,encoding='utf-8')
    result=dict(branch=BRANCH,base_commit=BASE,head=head,commits=commits,
        bundle=dict(path=bundle.relative_to(ROOT).as_posix(),sha256=file_hash(bundle),verified=True,clone_head_verified=True),
        runtime_archive=dict(path=archive.relative_to(ROOT).as_posix(),bytes=archive.stat().st_size,sha256=file_hash(archive),files_verified=len(members),all_member_hashes_verified=True,members=members),
        restored_model_sha256_verified=True,restored_predictions_and_cam_verified=True,restored_samples=16,original_absolute_dataset_not_used=True,
        future_sync_verified_against_local_bare_repo=True,github_pushed=False,pr_created=False,original_remote=git(['remote','get-url','origin']))
    (backup/'delivery_manifest.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print('Verified complete history, every runtime byte, independent model/data/CAM restore and future local sync.')
    print('HEAD:',head,'Runtime archive SHA256:',result['runtime_archive']['sha256'])


if __name__=='__main__':main()
