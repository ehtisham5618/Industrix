import csv
import io
import json
import subprocess
from pathlib import Path
from Backend.incidents.repository import ROOT,utc

def main():
    path=ROOT/'reports/ife_ui2_metrics.json';r=json.loads(path.read_text(encoding='utf-8'))
    tests=json.loads((ROOT/'IFE_UI2_Incident_Audit/reports/test_results.json').read_text(encoding='utf-8'))
    if r['overall']!='PASS' or not all(t['passed'] for t in tests.values()):raise RuntimeError('Final incident delivery requires genuine passing validation')
    r['tests']=tests;r['source_commit']=subprocess.check_output(['git','log','-1','--format=%H','--','Backend/incidents/service.py'],cwd=ROOT,text=True).strip()
    r['export_samples']=list(csv.DictReader((ROOT/'reports/ife_ui2_pdf_export_samples.csv').open(encoding='utf-8')))
    for sample in r['export_samples']:sample['seconds']=float(sample['seconds'])
    r['finalized_at_utc']=utc()
    from Experiment_Tracking.scripts.mlflow_utils import configure_tracking
    mlflow=configure_tracking(ROOT/'Experiment_Tracking/mlruns')
    with mlflow.start_run(run_name='IFE-UI2: local incident auditing and offline PDF exports') as run:
        mlflow.set_tags(dict(task='IFE-UI2',experiment_type='incident_logging_and_reporting',sprint='Sprint 4',status=r['overall'],config_version=r['version']))
        mlflow.log_params(dict(database='SQLite',pdf_engine='ReportLab',offline=True,
            model_version=r['sample']['detector_version'],alert_policy_version=r['sample']['alert_policy_version'],
            source_commit=r['source_commit'],incident_id=r['sample']['incident_id'],journal_mode=r['database']['journal_mode']))
        mlflow.log_metrics(dict(mean_fresh_export_seconds=r['fresh_pdf_seconds']['mean'],p95_export_seconds=r['fresh_pdf_seconds']['p95'],
            max_export_seconds=r['fresh_pdf_seconds']['max'],mean_actual_click_to_bytes_seconds=r['actual_button_to_pdf_bytes_seconds']['mean'],
            p95_actual_click_to_bytes_seconds=r['actual_button_to_pdf_bytes_seconds']['p95'],
            max_actual_click_to_bytes_seconds=r['actual_button_to_pdf_bytes_seconds']['max'],test_count=sum(t['tests'] for t in tests.values()),external_network_attempts=0))
        r['mlflow_run_id']=run.info.run_id;path.write_text(json.dumps(r,indent=2),encoding='utf-8')
        from .report import render
        render(r);mlflow.log_artifacts(str(path.parent));mlflow.log_artifacts(str(ROOT/'IFE_UI2_Incident_Audit/reports'))
    registry=ROOT/'Experiment_Tracking/experiments.csv';original=registry.read_bytes();existing=list(csv.DictReader(io.StringIO(original.decode())))
    if any(row['run_id']=='IFEUI2-EXP-001' for row in existing):raise RuntimeError('Incident audit registry row already exists')
    row=dict(run_id='IFEUI2-EXP-001',run_name='IFE-UI2: local incident auditing and offline PDF exports',sprint='Sprint 4',
        task='IFE-UI2',stage='Incident Audit',experiment_type='incident_logging_and_reporting',model_version=r['sample']['detector_version'],
        alert_policy_version=r['sample']['alert_policy_version'],model_architecture='YOLOv8s',num_classes=12,batch_size=1,imgsz=640,device='CPU',
        environment='Local SQLite and ReportLab; Windows CPU validation',best_weight_uri='Backend/best.pt',
        exported_weight_uri='Backend/weights/openvino_int8',source_script='IFE_UI2_Incident_Audit/validate.py',git_commit=r['source_commit'],
        status='validated_targets_met',tracking_origin='actual_local_incident_export_validation',
        confidence_config='Confidence_Calibration/configs/calibrated_thresholds.yaml',required_frames=15,window_size=15,
        notes=json.dumps(dict(mlflow_run_id=r['mlflow_run_id'],version=r['version'],overall=r['overall'],
            mean_pdf_seconds=r['fresh_pdf_seconds']['mean'],p95_pdf_seconds=r['fresh_pdf_seconds']['p95'],
            actual_click_max_seconds=r['actual_button_to_pdf_bytes_seconds']['max'],database='SQLite',pdf_engine='ReportLab',offline=True,
            report='reports/IFE_UI2_Incident_Export_Report.md'),separators=(',',':')))
    buffer=io.StringIO(newline='');writer=csv.DictWriter(buffer,fieldnames=list(existing[0]));writer.writerow({k:row.get(k,'') for k in existing[0]})
    registry.write_bytes(original+buffer.getvalue().encode())
    print(json.dumps(dict(status=r['overall'],source_commit=r['source_commit'],mlflow_run_id=r['mlflow_run_id']),indent=2))

if __name__=='__main__':main()
