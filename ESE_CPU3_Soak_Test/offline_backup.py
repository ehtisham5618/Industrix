"""Verified code/runtime recovery without organization repository access."""
import hashlib
import subprocess
import zipfile
from ESE_CPU1_Quantization.common import ROOT,digest,write_json

BRANCH='feature/atlantis-cpu-soak-test'
BASE='79a1d8cff0a95f6b2d1e0014c36dd60a4752c018'


def main():
    import json
    backup=ROOT/'ESE_CPU3_Soak_Test/backups';backup.mkdir(parents=True,exist_ok=True)
    commits=subprocess.check_output(['git','log','--format=%H%x09%s',BASE+'..'+BRANCH],cwd=ROOT,text=True).splitlines()
    if len(commits)!=2:raise RuntimeError('Exactly two CPU3 task commits required')
    report=json.loads((ROOT/'SED_3_Stress_Testing/reports/cpu_soak_report.json').read_text())
    if report['duration_actual_seconds']<3600 or report['status']!='completed':
        raise RuntimeError('Save final task delivery only after the real one-hour run')
    bundle=backup/'ESE_CPU3_complete_history.bundle'
    subprocess.run(['git','bundle','create',str(bundle),'--all'],cwd=ROOT,check=True)
    check=subprocess.run(['git','bundle','verify',str(bundle)],cwd=ROOT,check=True,text=True,
                         stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    (backup/'bundle_verification.txt').write_text(check.stdout,encoding='utf-8')
    head=subprocess.check_output(['git','rev-parse',BRANCH],cwd=ROOT,text=True).strip()
    probe=ROOT/'ESE_CPU3_Soak_Test/runtime'/('restore_probe_'+head[:7])
    if not probe.exists():subprocess.run(['git','clone','--quiet','--branch',BRANCH,str(bundle),str(probe)],check=True)
    restored=subprocess.check_output(['git','-C',str(probe),'rev-parse','HEAD'],text=True).strip()
    if restored!=head:raise RuntimeError('Bundle recovery HEAD mismatch')
    inputs=[ROOT/'Backend/best.pt',*[ROOT/'Backend/weights/openvino_int8'/n for n in ('model.xml','model.bin','metadata.yaml')],
        ROOT/'data/test_factory_clip.mp4',ROOT/'Confidence_Calibration/benchmark/media/chemical_hazard_01_hazmat_training.webm',
        ROOT/'Confidence_Calibration/benchmark/media/no_helmet_01_workers_roof.webm']
    inputs += [p for p in (ROOT/'Experiment_Tracking/mlruns').rglob('*') if p.is_file()]
    inputs += [p for p in (ROOT/'SED_2_Alert_Escalation/runtime').glob('cpu_soak*_alert_events*.jsonl') if p.is_file()]
    archive=backup/'ESE_CPU3_local_runtime.zip'
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
        measured_run_status=report['status'],acceptance=report['overall'],duration_seconds=report['duration_actual_seconds'],
        pushed=False,pr_created=False,remote=subprocess.check_output(['git','remote','get-url','origin'],cwd=ROOT,text=True).strip(),
        sync_command='git push -u origin '+BRANCH)
    write_json(backup/'delivery_manifest.json',result);print(json.dumps(result,indent=2))


if __name__=='__main__':main()
