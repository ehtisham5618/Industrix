"""Verified two-commit history and independent local-runtime recovery archive."""
import hashlib
import json
import sqlite3
import subprocess
import zipfile
from .prepare import ROOT,TASK
from ESE_CPU1_Quantization.common import digest

BRANCH='feature/atlantis-demo-packaging'
BASE='bfbc4e6d6f07e3f4606f4b7d90852b64e4e3b015'

def main():
    backup=TASK/'backups';backup.mkdir(parents=True,exist_ok=True)
    commits=subprocess.check_output(['git','log','--format=%H%x09%s',BASE+'..'+BRANCH],cwd=ROOT,text=True).splitlines()
    if len(commits)!=2:raise RuntimeError('Exactly two IFE-UI3 commits required')
    metrics=json.loads((ROOT/'reports/ife_ui3_demo_metrics.json').read_text(encoding='utf-8'))
    if metrics['status']!='completed':raise RuntimeError('Only a verified actual recording can be delivered')
    bundle=backup/'IFE_UI3_complete_history.bundle'
    subprocess.run(['git','bundle','create',str(bundle),'--all'],cwd=ROOT,check=True)
    check=subprocess.run(['git','bundle','verify',str(bundle)],cwd=ROOT,check=True,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    (backup/'bundle_verification.txt').write_text(check.stdout,encoding='utf-8')
    head=subprocess.check_output(['git','rev-parse',BRANCH],cwd=ROOT,text=True).strip()
    probe=TASK/'runtime'/('restore_probe_'+head[:7])
    if probe.exists():raise RuntimeError('Use a fresh restore probe; do not overwrite an existing directory')
    subprocess.run(['git','clone','--quiet','--branch',BRANCH,str(bundle),str(probe)],check=True)
    restored=subprocess.check_output(['git','-C',str(probe),'rev-parse','HEAD'],text=True).strip()
    assert restored==head
    inputs=[ROOT/'Backend/best.pt',*[ROOT/'Backend/weights/openvino_int8'/n for n in ('model.xml','model.bin','metadata.yaml')],
        ROOT/'Backend/weights/onnx_fp16/best_fp16.onnx',ROOT/'data/test_factory_clip.mp4',
        ROOT/'Confidence_Calibration/benchmark/media/chemical_hazard_01_hazmat_training.webm',
        ROOT/'Confidence_Calibration/benchmark/media/no_helmet_01_workers_roof.webm',
        TASK/'runtime/textile_demo.mp4',TASK/'runtime/hazard_ready.mp4',TASK/'runtime/hazard_timed.mp4',TASK/'runtime/workers_demo.mp4',ROOT/metrics['recording']['path']]
    runtime=ROOT/metrics['runtime']
    inputs += [p for p in runtime.rglob('*') if p.is_file() and p.suffix not in ('.db','.db-wal','.db-shm') and not p.name.startswith('events.db')]
    inputs += [p for p in (ROOT/'Experiment_Tracking/mlruns').rglob('*') if p.is_file()]
    inputs=list(dict.fromkeys(inputs))
    copied=backup/'consistent_demo_database.db'
    source=sqlite3.connect(runtime/'events.db');target=sqlite3.connect(copied)
    try:source.backup(target)
    finally:target.close();source.close()
    with sqlite3.connect(copied) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert db.execute('SELECT snapshot_sha256 FROM incidents WHERE incident_id=?',(metrics['incident']['incident_id'],)).fetchone()[0]==metrics['incident']['snapshot_sha256']
    db_name=(runtime/'events.db').relative_to(ROOT).as_posix()
    archive=backup/'IFE_UI3_local_runtime.zip';members=[]
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as stream:
        for path in inputs:
            name=path.relative_to(ROOT).as_posix();stream.write(path,name);members.append(dict(path=name,bytes=path.stat().st_size,sha256=digest(path)))
        stream.write(copied,db_name);members.append(dict(path=db_name,bytes=copied.stat().st_size,sha256=digest(copied)))
    with zipfile.ZipFile(archive) as stream:
        assert stream.testzip() is None
        for member in members:
            with stream.open(member['path']) as item:assert hashlib.file_digest(item,'sha256').hexdigest()==member['sha256']
        # Exercise actual recovery of the DB, native crop, local model and MP4.
        selected=[db_name,metrics['recording']['path'].replace('\\','/'),
            'Backend/weights/openvino_int8/model.xml','Backend/weights/openvino_int8/model.bin','Backend/weights/openvino_int8/metadata.yaml']
        selected += [m['path'] for m in members if '/snapshots/' in m['path']]
        for name in selected:
            target=probe/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(stream.read(name))
    with sqlite3.connect(probe/db_name) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert db.execute('SELECT class_name FROM incidents WHERE incident_id=?',(metrics['incident']['incident_id'],)).fetchone()[0]=='fire'
    info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(probe/metrics['recording']['path'])],text=True))
    assert info['streams'][0]['width']==1920 and 105<=float(info['format']['duration'])<=135
    for key in ('model.xml','model.bin','metadata.yaml'):
        assert digest(probe/'Backend/weights/openvino_int8'/key)==digest(ROOT/'Backend/weights/openvino_int8'/key)
    result=dict(branch=BRANCH,base_commit=BASE,commits=commits,
        bundle=dict(path=bundle.relative_to(ROOT).as_posix(),sha256=digest(bundle),verified=True,clone_restore_verified=True,restored_head=restored),
        runtime_archive=dict(path=archive.relative_to(ROOT).as_posix(),sha256=digest(archive),files_verified=len(members),sqlite_consistent_backup=True,
            restored_database_verified=True,restored_video_verified=True,restored_model_hashes_verified=True,members=members),
        recording=metrics['recording'],pushed=False,pr_created=False,merged=False,tag_created=False,
        remote=subprocess.check_output(['git','remote','get-url','origin'],cwd=ROOT,text=True).strip(),sync_command='git push -u origin '+BRANCH)
    (backup/'delivery_manifest.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='runtime_archive'},indent=2))
    print('Runtime files verified:',len(members),'Archive SHA256:',digest(archive))

if __name__=='__main__':main()
