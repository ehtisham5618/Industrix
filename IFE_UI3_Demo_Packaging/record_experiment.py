"""Record measured integration in the existing CSV/local MLflow lineage."""
import csv
import json
import subprocess
from .prepare import ROOT,TASK
from .offline_server import install_guard

def main():
    install_guard()
    from Experiment_Tracking.scripts.mlflow_utils import configure_tracking
    path=ROOT/'Experiment_Tracking/experiments.csv'
    with path.open(newline='',encoding='utf-8') as source:reader=csv.DictReader(source);fields=reader.fieldnames;rows=list(reader)
    if any(row['task']=='IFE-UI3' for row in rows):raise RuntimeError('IFE-UI3 is already recorded; refusing a duplicate run')
    m=json.loads((ROOT/'reports/ife_ui3_demo_metrics.json').read_text(encoding='utf-8'));assert m['status']=='completed'
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    mlflow=configure_tracking(ROOT/'Experiment_Tracking/mlruns')
    with mlflow.start_run(run_name='IFE-UI3 real CPU end-to-end demo') as run:
        mlflow.set_tags(dict(task='IFE-UI3',sprint='Sprint 4',experiment_type='end_to_end_demo',status='local_pass_release_pending',overall_dod='FAIL',tracking_origin='measured_local_run'))
        mlflow.log_params(dict(model_version='cme-opt2-focal-cosine-12class-v1',policy_version='cmeopt3-bytetrack15-v1',
            demo_version='IFEUI3-local-demo-v1',device='CPU',precision='INT8',streams=3,persist_frames=15,sample_every=4,source_commit=commit,
            physical_wifi_disconnected=False,external_runtime_apis_required=0,upload='manual action required',merge='pending revoked access'))
        mlflow.log_metrics(dict(recording_seconds=m['recording']['duration_seconds'],operational_fps_mean=m['performance']['operational_evaluated_fps']['mean'],
            model_inference_latest_mean_ms=m['telemetry'][-1]['model_inference_mean_ms'],model_inference_latest_p95_ms=m['telemetry'][-1]['model_inference_p95_ms'],
            ui_delivery_mean_ms=m['performance']['ui_delivery_ms']['mean'],pdf_click_to_bytes_seconds=m['pdf_export']['click_to_bytes_seconds']))
        for asset in ['reports/IFE_UI3_End_to_End_Demo_Report.md','reports/ife_ui3_demo_metrics.json','reports/IFE_UI3_E2E_Test_Result.txt',
            'IFE_UI3_Demo_Packaging/reports/regression_results.json']:mlflow.log_artifact(str(ROOT/asset))
        row={field:'' for field in fields};row.update(run_id=run.info.run_id,run_name='IFE-UI3 real CPU end-to-end demo',sprint='Sprint 4',task='IFE-UI3',
            stage='End-to-end validation and recording',experiment_type='end_to_end_demo',model_version='cme-opt2-focal-cosine-12class-v1',
            alert_policy_version='cmeopt3-bytetrack15-v1',model_architecture='YOLOv8s',dataset='Local labelled demo footage',
            dataset_version='combined-12class-v3-hardnegative demo fixtures',num_classes='12',imgsz='640',device='cpu',
            environment='Windows 11 / Intel i5-7200U / guarded loopback',exported_weight_uri='ESE_CPU1_Quantization/reports/artifact_manifest.json',
            source_script='IFE_UI3_Demo_Packaging/record_demo.py',git_commit=commit,status='local_pass_release_pending',tracking_origin='measured_local_run',
            confidence_config='Confidence_Calibration/configs/calibrated_thresholds.yaml',required_frames='15',
            notes='Actual 1080p recording and PDF; full DoD FAIL: physical disconnect not performed, upload pending, organization access revoked, merge/tag pending. Original numerical gates remain unmet.')
    with path.open('a',newline='',encoding='utf-8') as output:csv.DictWriter(output,fieldnames=fields).writerow(row)
    (TASK/'reports/experiment_tracking.json').write_text(json.dumps(dict(run_id=row['run_id'],source_commit=commit,model_version=row['model_version'],status=row['status'],overall_dod='FAIL'),indent=2),encoding='utf-8')
    print('Recorded existing-registry run:',row['run_id'])

if __name__=='__main__':main()
