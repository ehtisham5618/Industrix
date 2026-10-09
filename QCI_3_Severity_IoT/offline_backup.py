"""Standard-library-only complete history and independently restored runtime proof."""
from pathlib import Path
import hashlib
import json
import sqlite3
import subprocess
import sys
import uuid
import zipfile

ROOT=Path(__file__).resolve().parents[1];TASK=ROOT/'QCI_3_Severity_IoT'
BRANCH='feature/sprint2-qci3-severity-iot-alerts';BASE='9daaa97e0f3c674095ec98a79f8d215a18bc3b2e'

def git(args,cwd=ROOT):return subprocess.check_output(['git',*args],cwd=cwd,text=True,stderr=subprocess.STDOUT).strip()
def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def main():
    if git(['status','--porcelain']):raise ValueError('Commit deliverables before recovery packaging')
    commits=git(['log','--format=%H%x09%s',BASE+'..'+BRANCH]).splitlines()
    if len(commits)!=2:raise ValueError('Exactly two QCI-3 commits required')
    backup=TASK/'backups';backup.mkdir(parents=True,exist_ok=True)
    bundle=backup/'QCI_3_complete_history.bundle';git(['bundle','create',str(bundle),'--all'])
    verification=git(['bundle','verify',str(bundle)])
    head=git(['rev-parse',BRANCH]);probe=TASK/'runtime'/('restore_'+head[:7]+'_'+uuid.uuid4().hex[:6])
    git(['clone','--quiet','--branch',BRANCH,str(bundle),str(probe)])
    assert git(['rev-parse','HEAD'],probe)==head
    archive=backup/'QCI_3_local_runtime.zip';members=[]
    files=[ROOT/'QCI_2_Defect_Classifier/runtime/run_v1/best.pt',TASK/'runtime/fresh_predictions.json',
        ROOT/'reports/qci1/segmentation/samples.jsonl',ROOT/'reports/qci1/segmentation/dataset_manifest.json']
    directories=[ROOT/'QCI_1_Surface_Defect_Segmentation/runtime/segmentation_dataset',ROOT/'reports/qci3',
        ROOT/'Backend/weights/openvino_int8',ROOT/'Backend/weights/onnx_fp16',TASK/'runtime/heatmaps']
    for name in ('loopback_demo.json','memory_profile.json'):
        report=json.loads((ROOT/'reports/qci3'/name).read_text())
        db=ROOT/report.get('audit_database',report.get('runtime_database'))
        snapshot=TASK/'runtime/backup_snapshots'/db.parent.name/'events.db';snapshot.parent.mkdir(parents=True,exist_ok=True)
        source=sqlite3.connect(db);destination=sqlite3.connect(snapshot)
        try:source.backup(destination)
        finally:destination.close();source.close()
        files.append(snapshot)
    tracking=json.loads((ROOT/'reports/qci3/experiment_tracking.json').read_text())
    for run in (ROOT/'Experiment_Tracking/mlruns').glob('*/'+tracking['run_id']):
        directories.append(run);files.append(run.parent/'meta.yaml')
    for directory in directories:files.extend(p for p in directory.rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_STORED,allowZip64=True) as zipped:
        for path in sorted(set(files)):
            name=path.relative_to(ROOT).as_posix();zipped.write(path,name)
            members.append({'path':name,'bytes':path.stat().st_size,'sha256':digest(path)})
    with zipfile.ZipFile(archive) as zipped:
        for member in members:
            name=member['path'];relative=Path(name)
            if relative.is_absolute() or '..' in relative.parts:raise ValueError('Unsafe archive member')
            with zipped.open(name) as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==member['sha256']
            zipped.extract(name,probe)
    recovered=subprocess.run([sys.executable,'-X','utf8','-c',
        'from QCI_3_Severity_IoT.verify import fresh_predictions,demo; import json; p=fresh_predictions(); r=demo(p); print(json.dumps(dict(restored_real_model=True,received=r["requests_received"],acknowledged=r["acknowledged_activations"],duplicates=r["duplicate_activations"])))'],
        cwd=probe,capture_output=True,text=True,encoding='utf-8',timeout=120)
    (backup/'restored_model_and_webhook_terminal.txt').write_text(recovered.stdout+recovered.stderr,encoding='utf-8')
    if recovered.returncode:raise RuntimeError('Recovered real classifier/webhook verification failed')
    counts=[]
    for snapshot in (probe/'QCI_3_Severity_IoT/runtime/backup_snapshots').glob('*/events.db'):
        db=sqlite3.connect(snapshot)
        try:
            assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            counts.append({'database':snapshot.relative_to(probe).as_posix(),'events':db.execute('SELECT COUNT(*) FROM qci3_events').fetchone()[0],
                'audit':db.execute('SELECT COUNT(*) FROM qci3_audit').fetchone()[0]})
        finally:db.close()
    remote=TASK/'runtime'/('sync_proof_'+head[:7]+'_'+uuid.uuid4().hex[:6]+'.git')
    git(['init','--quiet','--bare',str(remote)])
    pushed=subprocess.run(['powershell','-NoProfile','-File',str(probe/'QCI_3_Severity_IoT/sync_when_access_returns.ps1'),'-Remote',str(remote)],
        cwd=probe,capture_output=True,text=True,encoding='utf-8',timeout=30)
    if pushed.returncode:raise RuntimeError('Normal future sync helper failed local bare-repository proof')
    assert git(['--git-dir',str(remote),'rev-parse',BRANCH])==head
    result={'branch':BRANCH,'base':BASE,'head':head,'task_commits':commits,'git_bundle_verified':True,
        'bundle_sha256':digest(bundle),'runtime_archive_sha256':digest(archive),'runtime_archive_bytes':archive.stat().st_size,
        'all_runtime_members_hash_verified':True,'members':members,'restored_model_and_webhook_verified':True,
        'restored_audit_databases':counts,'normal_sync_helper_verified_against_local_bare_repo':True,
        'github_push_performed':False,'restore_probe':str(probe),'bundle_verification':verification}
    (backup/'delivery_manifest.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('head','git_bundle_verified','runtime_archive_bytes','restored_model_and_webhook_verified','normal_sync_helper_verified_against_local_bare_repo')}))

if __name__=='__main__':main()
