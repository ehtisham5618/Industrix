"""Append measured monitoring lineage to existing local MLflow and CSV tracking."""
import csv
import json
from pathlib import Path
import subprocess
from QCI_3_Severity_IoT.offline import loopback_only

ROOT=Path(__file__).resolve().parents[1];REPORTS=ROOT/'reports/qci4'

def main():
    from Backend.offline_policy import configure_local_runtime
    configure_local_runtime()
    from Experiment_Tracking.scripts.mlflow_utils import configure_tracking
    demo=json.loads((REPORTS/'failover_demo.json').read_text());memory=json.loads((REPORTS/'memory_profile.json').read_text())
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    notes={'telemetry_policy_version':'qci4-edge-policy-v1','cloud_protocol_version':'qci4-sync-v1',
        'QCI2_model_version':'qci2-kolektor-resnet18-v1','QCI3_policy_version':'qci3-research-v1',
        'model_sha256':demo['model_sha256'],'metadata_only':True,'production_cloud_endpoint_provided':False,
        'sample_interval_seconds':2,'memory_drift_percent':memory['matched_window_drift_percent'],
        'repo_cpu_gates_met':False,'source_commit':commit}
    with loopback_only():
        mlflow=configure_tracking(ROOT/'Experiment_Tracking/mlruns')
        with mlflow.start_run(run_name='QCI-4 real local telemetry and cloud outage recovery') as run:
            mlflow.set_tags({'task':'QCI-4','sprint':'Sprint 2','overall_dod':'FAIL','implementation':'PASS','cloud_validation':'local_mock_only'})
            mlflow.log_params(notes)
            mlflow.log_metrics({'memory_drift_percent':memory['matched_window_drift_percent'],
                'telemetry_mean_ms':memory['telemetry_latency']['mean_ms'],'spool_batch_mean_ms':memory['spool_enqueue_latency']['mean_ms'],
                'cloud_post_mean_ms':memory['cloud_post_latency']['mean_ms'],'failure_detection_ms':demo['failure_detection_ms'],
                'recovery_ms':demo['recovery_ms'],'fresh_inferences_during_outage':demo['fresh_model_predictions_during_outage'],
                'logical_delivered_profile':memory['logical_items_delivered'],'duplicate_logical_deliveries':0})
            for name in ('failover_demo.json','memory_profile.json','pytest_output.txt'):
                mlflow.log_artifact(str(REPORTS/name))
            run_id=run.info.run_id
    path=ROOT/'Experiment_Tracking/experiments.csv'
    with path.open(encoding='utf-8',newline='') as stream:
        reader=csv.DictReader(stream);fields=reader.fieldnames
        if any(r['task']=='QCI-4' for r in reader):raise ValueError('QCI-4 already recorded; no duplicate history written')
    row=dict(run_id=run_id,run_name='QCI-4 real local telemetry and cloud outage recovery',sprint='Sprint 2',task='QCI-4',
        stage='Optional edge health and bounded metadata sync',experiment_type='edge_telemetry_failover',model_version='qci2-kolektor-resnet18-v1',
        alert_policy_version='qci3-research-v1',model_architecture='QCI-2/QCI-3 consumer; no cloud inference',num_classes=2,device='cpu',
        source_script='QCI_4_Edge_Telemetry/verify.py',git_commit=commit,status='local_mock_verified_inherited_cpu_release_gates_unmet',
        tracking_origin='measured_local_run',confidence_config='QCI_4_Edge_Telemetry/configs/local_safe.json',notes=json.dumps(notes,separators=(',',':')))
    with path.open('a',encoding='utf-8',newline='') as stream:csv.DictWriter(stream,fieldnames=fields).writerow({f:row.get(f,'') for f in fields})
    result={'run_id':run_id,**notes};(REPORTS/'experiment_tracking.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result))
if __name__=='__main__':main()
