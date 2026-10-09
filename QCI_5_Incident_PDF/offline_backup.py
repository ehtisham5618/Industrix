"""Verify complete Git history and independently restore the PDF's actual local inputs."""
from contextlib import closing
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import uuid
import zipfile

ROOT=Path(__file__).resolve().parents[1];TASK=ROOT/'QCI_5_Incident_PDF'
BRANCH='feature/sprint2-qci5-incident-pdf';BASE='a11e10a917392a94d05645a0d7a55b5dd70bb9b0'
def git(args,cwd=ROOT):return subprocess.check_output(['git',*args],cwd=cwd,text=True,stderr=subprocess.STDOUT).strip()
def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def main():
    if git(['status','--porcelain']):raise ValueError('Commit task deliverables before packaging')
    commits=git(['log','--format=%H%x09%s',BASE+'..'+BRANCH]).splitlines()
    if len(commits)!=2:raise ValueError('Exactly two QCI-5 task commits required')
    backup=TASK/'backups';backup.mkdir(parents=True,exist_ok=True)
    bundle=backup/'QCI_5_complete_history.bundle';git(['bundle','create',str(bundle),'--all'])
    verification=git(['bundle','verify',str(bundle)]);head=git(['rev-parse',BRANCH])
    clone=TASK/'runtime'/('restore_'+head[:7]+'_'+uuid.uuid4().hex[:6])
    git(['clone','--quiet','--branch',BRANCH,str(bundle),str(clone)]);assert git(['rev-parse','HEAD'],clone)==head
    git(['remote','set-url','origin','https://github.com/devlogixtechnology/industirx.git'],clone)
    demo=json.loads((ROOT/'reports/qci5/pdf_demo.json').read_text())
    database=ROOT/demo['lineage']['database'];snapshot=TASK/'runtime/backup_snapshots/events.db';snapshot.parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(database)) as source,closing(sqlite3.connect(snapshot)) as destination:source.backup(destination)
    files={snapshot:database.relative_to(ROOT).as_posix()}
    for name in ('sample_config.json','sample_evidence.json','sample_lineage.json'):
        path=TASK/'runtime'/name;files[path]=path.relative_to(ROOT).as_posix()
    for evidence in demo['lineage']['evidence']:
        path=ROOT/evidence['path'];files[path]=evidence['path']
    for path in (ROOT/'reports/qci5').rglob('*'):
        if path.is_file():files[path]=path.relative_to(ROOT).as_posix()
    tracking=json.loads((ROOT/'reports/qci5/experiment_tracking.json').read_text())
    for run in (ROOT/'Experiment_Tracking/mlruns').glob('*/'+tracking['run_id']):
        for path in run.rglob('*'):
            if path.is_file():files[path]=path.relative_to(ROOT).as_posix()
        files[run.parent/'meta.yaml']=(run.parent/'meta.yaml').relative_to(ROOT).as_posix()
    members=[];archive=backup/'QCI_5_local_runtime.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,allowZip64=True) as zipped:
        for path,name in sorted(files.items(),key=lambda item:item[1]):
            zipped.write(path,name);members.append(dict(path=name,bytes=path.stat().st_size,sha256=digest(path)))
    with zipfile.ZipFile(archive) as zipped:
        for member in members:
            name=member['path'];target=(clone/name).resolve()
            if not target.is_relative_to(clone.resolve()):raise ValueError('Unsafe archive member')
            with zipped.open(name) as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==member['sha256']
            zipped.extract(name,clone)
    # Original weights/dataset are deliberately unnecessary: PDF exports consume
    # persisted results, exact evidence and local fonts, without running a model.
    code='''from pathlib import Path
import asyncio,json
from QCI_5_Incident_PDF.adapter import Adapter,configuration,ROOT
from QCI_5_Incident_PDF.service import PDFService
from QCI_5_Incident_PDF.verify import api_export
from QCI_1_Surface_Defect_Segmentation.offline import no_network
from pypdf import PdfReader
demo=json.loads((ROOT/'reports/qci5/pdf_demo.json').read_text());key=demo['incident_id']
with no_network() as audit:
 service=PDFService(Adapter(config=configuration()));report=service.adapter.load(key)
 assert all((ROOT/e.path).resolve().is_relative_to(ROOT) for e in report.evidence)
 result=service.generate(key);assert result.status=='SUCCESS',result.model_dump_json()
 with PdfReader(result.output_path) as pdf:
  text=' '.join(p.extract_text() for p in pdf.pages)
  assert key in text and 'CRITICAL' in text and 'ACKNOWLEDGED' in text
  assert sum(len(p.images) for p in pdf.pages)==2
 assert audit.attempts==0
with asyncio.Runner() as runner:
 runner.get_loop()
 with no_network() as audit:response=runner.run(api_export(service,key));assert audit.attempts==0
print(json.dumps(dict(restored_pdf_and_existing_api_verified=True,incident_id=key,evidence_files=2,external_socket_attempts=0,pdf_size_bytes=result.size_bytes,original_repository_data_used=False)))
'''
    import os
    env={**os.environ,'QCI5_CONFIG':str(clone/'QCI_5_Incident_PDF/runtime/sample_config.json')}
    check=subprocess.run([sys.executable,'-X','utf8','-c',code],cwd=clone,env=env,capture_output=True,text=True,encoding='utf-8',timeout=90)
    (backup/'cold_clone_pdf_terminal.txt').write_text(check.stdout+check.stderr,encoding='utf-8')
    if check.returncode:raise RuntimeError('Cold-clone PDF/API verification failed; actual terminal retained')
    restored=json.loads(check.stdout)
    with closing(sqlite3.connect(clone/demo['lineage']['database'])) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        counts={table:db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in ('qci3_events','qci3_audit')}
    remote=TASK/'runtime'/('sync_proof_'+head[:7]+'_'+uuid.uuid4().hex[:6]+'.git');git(['init','--quiet','--bare',str(remote)])
    push=subprocess.run(['powershell','-NoProfile','-File',str(clone/'QCI_5_Incident_PDF/sync_when_access_returns.ps1'),'-Remote',str(remote)],cwd=clone,capture_output=True,text=True,encoding='utf-8',timeout=30)
    (backup/'local_push_proof.txt').write_text(push.stdout+push.stderr,encoding='utf-8')
    if push.returncode:raise RuntimeError('Normal future sync helper failed local bare-repository proof')
    assert git(['--git-dir',str(remote),'rev-parse',BRANCH])==head
    result=dict(branch=BRANCH,base=BASE,head=head,task_commits=commits,bundle_sha256=digest(bundle),bundle_verified=True,
        bundle_verification=verification,runtime_archive_sha256=digest(archive),runtime_archive_bytes=archive.stat().st_size,
        all_runtime_members_hash_verified=True,members=members,cold_clone=restored,restored_database_integrity='ok',restored_database_counts=counts,
        normal_sync_helper_verified_against_local_bare_repository=True,github_push_performed=False,
        model_execution_required=False,weights_required_for_pdf_restore=False,restore_probe=str(clone))
    (backup/'delivery_manifest.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('head','runtime_archive_bytes','bundle_verified','cold_clone','normal_sync_helper_verified_against_local_bare_repository')}))
if __name__=='__main__':main()
