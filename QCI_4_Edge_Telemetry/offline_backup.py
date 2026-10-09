"""Stdlib-only history/runtime packaging and genuine cold-clone failover recovery."""
from pathlib import Path
import hashlib
import json
import sqlite3
import subprocess
import sys
import uuid
import zipfile

ROOT=Path(__file__).resolve().parents[1];TASK=ROOT/'QCI_4_Edge_Telemetry'
BRANCH='feature/sprint2-qci4-edge-telemetry-failover';BASE='bf50aabefba2812036b2de03cd6c718af995d1d0'

def git(args,cwd=ROOT):return subprocess.check_output(['git',*args],cwd=cwd,text=True,stderr=subprocess.STDOUT).strip()
def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def main():
    if git(['status','--porcelain']):raise ValueError('Commit deliverables before packaging')
    commits=git(['log','--format=%H%x09%s',BASE+'..'+BRANCH]).splitlines()
    if len(commits)!=2:raise ValueError('Exactly two QCI-4 commits required')
    backup=TASK/'backups';backup.mkdir(parents=True,exist_ok=True)
    bundle=backup/'QCI_4_complete_history.bundle';git(['bundle','create',str(bundle),'--all'])
    verification=git(['bundle','verify',str(bundle)]);head=git(['rev-parse',BRANCH])
    probe=TASK/'runtime'/('restore_'+head[:7]+'_'+uuid.uuid4().hex[:6])
    git(['clone','--quiet','--branch',BRANCH,str(bundle),str(probe)]);assert git(['rev-parse','HEAD'],probe)==head
    files=[ROOT/'QCI_2_Defect_Classifier/runtime/run_v1/best.pt',
        ROOT/'reports/qci1/segmentation/samples.jsonl',ROOT/'reports/qci1/segmentation/dataset_manifest.json']
    directories=[ROOT/'QCI_1_Surface_Defect_Segmentation/runtime/segmentation_dataset',ROOT/'reports/qci4']
    restored_databases=[]
    for name,field in (('failover_demo.json','database'),('memory_profile.json','runtime_database')):
        report=json.loads((ROOT/'reports/qci4'/name).read_text());original=ROOT/report[field]
        for database in (original,ROOT/report['receiver_database']):
            snapshot=TASK/'runtime/backup_snapshots'/database.parent.name/database.name;snapshot.parent.mkdir(parents=True,exist_ok=True)
            source=sqlite3.connect(database);destination=sqlite3.connect(snapshot)
            try:source.backup(destination)
            finally:destination.close();source.close()
            files.append(snapshot);restored_databases.append(snapshot.relative_to(ROOT).as_posix())
    tracking=json.loads((ROOT/'reports/qci4/experiment_tracking.json').read_text())
    for run in (ROOT/'Experiment_Tracking/mlruns').glob('*/'+tracking['run_id']):directories.append(run);files.append(run.parent/'meta.yaml')
    for directory in directories:files.extend(p for p in directory.rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    members=[];archive=backup/'QCI_4_local_runtime.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_STORED,allowZip64=True) as zipped:
        for path in sorted(set(files)):
            name=path.relative_to(ROOT).as_posix();zipped.write(path,name);members.append(dict(path=name,bytes=path.stat().st_size,sha256=digest(path)))
    with zipfile.ZipFile(archive) as zipped:
        for member in members:
            relative=Path(member['path'])
            if relative.is_absolute() or '..' in relative.parts:raise ValueError('Unsafe archive member')
            with zipped.open(member['path']) as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==member['sha256']
            zipped.extract(member['path'],probe)
    check=subprocess.run([sys.executable,'-X','utf8','-u','-m','QCI_4_Edge_Telemetry.verify','demo'],cwd=probe,capture_output=True,text=True,encoding='utf-8',timeout=150)
    (backup/'restored_model_failover_terminal.txt').write_text(check.stdout+check.stderr,encoding='utf-8')
    if check.returncode:raise RuntimeError('Cold-clone actual classifier/alert/failover verification failed')
    demo=json.loads((probe/'reports/qci4/failover_demo.json').read_text())
    assert demo['fresh_model_predictions_during_outage']==12 and demo['event_summaries_delivered']==18 and demo['duplicate_logical_deliveries']==0
    assert all((probe/p).resolve().is_relative_to(probe.resolve()) for p in demo['source_images_used'])
    audit=[]
    for name in restored_databases:
        db=sqlite3.connect(probe/name)
        try:
            assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            counts={table:db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in
                ('qci4_spool','qci4_receipts','qci4_log','qci3_events','receipts') if table in tables}
            audit.append({'database':name,'counts':counts,'integrity':'ok'})
        finally:db.close()
    remote=TASK/'runtime'/('sync_proof_'+head[:7]+'_'+uuid.uuid4().hex[:6]+'.git');git(['init','--quiet','--bare',str(remote)])
    pushed=subprocess.run(['powershell','-NoProfile','-File',str(probe/'QCI_4_Edge_Telemetry/sync_when_access_returns.ps1'),'-Remote',str(remote)],cwd=probe,capture_output=True,text=True,encoding='utf-8',timeout=30)
    if pushed.returncode:raise RuntimeError('Normal future push helper failed local bare-repository proof')
    assert git(['--git-dir',str(remote),'rev-parse',BRANCH])==head
    result={'branch':BRANCH,'base':BASE,'head':head,'task_commits':commits,'bundle_sha256':digest(bundle),
        'runtime_archive_sha256':digest(archive),'runtime_archive_bytes':archive.stat().st_size,'members':members,
        'git_bundle_verified':True,'all_runtime_members_hash_verified':True,'cold_clone_model_alert_failover_verified':True,
        'original_repository_data_used':False,'restored_databases':audit,'normal_sync_helper_verified_against_local_bare_repo':True,
        'github_push_performed':False,'restore_probe':str(probe),'bundle_verification':verification}
    (backup/'delivery_manifest.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('head','runtime_archive_bytes','git_bundle_verified','cold_clone_model_alert_failover_verified','normal_sync_helper_verified_against_local_bare_repo')}))
if __name__=='__main__':main()
