"""Record measured alarm evidence in the existing local MLflow/CSV registries."""
import csv
import json
from pathlib import Path
import subprocess
from .offline import loopback_only

ROOT=Path(__file__).resolve().parents[1];REPORTS=ROOT/'reports/qci3'

def append(path,values,key):
    with path.open(encoding='utf-8',newline='') as stream:
        reader=csv.DictReader(stream);fields=reader.fieldnames
        if any(row[key]==str(values[key]) for row in reader):raise ValueError('Duplicate registry identity')
    with path.open('a',encoding='utf-8',newline='') as stream:
        csv.DictWriter(stream,fieldnames=fields).writerow({f:values.get(f,'') for f in fields})

def main():
    from Backend.offline_policy import configure_local_runtime
    configure_local_runtime()
    from Experiment_Tracking.scripts.mlflow_utils import configure_tracking
    demo=json.loads((REPORTS/'loopback_demo.json').read_text());memory=json.loads((REPORTS/'memory_profile.json').read_text())
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    policy='qci3-research-v1';model='qci2-kolektor-resnet18-v1'
    notes={'state_machine_version':'qci3-state-machine-v1','webhook_policy_version':'qci3-webhook-v1',
        'model_version':model,'rules_version':policy,'demo_policy_version':demo['policy']['policy_version'],
        'dataset_license':'CC BY-NC-SA 4.0','use_scope':'user-confirmed noncommercial research and evaluation',
        'memory_drift_percent':memory['matched_window_drift_percent'],'core_latency_unit':'milliseconds',
        'duplicate_activations':0,'hardware_siren_validated':False,'repo_cpu_gates_met':False}
    with loopback_only():
        mlflow=configure_tracking(ROOT/'Experiment_Tracking/mlruns')
        with mlflow.start_run(run_name='QCI-3 measured local severity and siren bridge') as run:
            mlflow.set_tags({'task':'QCI-3','sprint':'Sprint 2','overall_dod':'FAIL','feature_implementation':'PASS','use_scope':'noncommercial_research'})
            mlflow.log_params({**notes,'source_commit':commit,'timeout_seconds':1,'max_attempts':3,'backoff_seconds':'.1,.2'})
            mlflow.log_metrics({'core_mean_ms':memory['core_latency']['mean_ms'],'core_p95_ms':memory['core_latency']['p95_ms'],
                'http_mean_ms':demo['http_latency']['mean_ms'],'http_p95_ms':demo['http_latency']['p95_ms'],
                'rss_drift_percent':memory['matched_window_drift_percent'],'mock_requests':demo['requests_received'],
                'acknowledged_activations':demo['acknowledged_activations'],'duplicate_activations':0})
            for name in ('loopback_demo.json','memory_profile.json','cpu_acceptance_followup.json','pytest_output.txt'):
                mlflow.log_artifact(str(REPORTS/name))
            run_id=run.info.run_id
    note=json.dumps(notes,separators=(',',':'))
    append(ROOT/'Experiment_Tracking/alert_policy_registry.csv',dict(policy_version=policy,sprint='Sprint 2',task='QCI-3',
        detector_model_version=model,threshold_config='QCI_3_Severity_IoT/configs/local_research.json',
        clear_policy='explicit resolution; recurrence new activation ID',status='research_verified_cpu_release_gates_unmet',
        benchmark='actual_qci2_loopback_bridge_and_5500_events',mean_latency=memory['core_latency']['mean_ms'],notes=note),'policy_version')
    append(ROOT/'Experiment_Tracking/experiments.csv',dict(run_id=run_id,run_name='QCI-3 measured local severity and siren bridge',
        sprint='Sprint 2',task='QCI-3',stage='Local quality event escalation and durable siren webhook',experiment_type='alert_escalation',
        model_version=model,alert_policy_version=policy,model_architecture='QCI-2 consumer; no inference in alarm engine',
        dataset='QCI-2 actual KolektorSDD outputs',dataset_version='QCI-1-local-segmentation-v1',num_classes=2,device='cpu',
        source_script='QCI_3_Severity_IoT/verify.py',git_commit=commit,status='research_verified_cpu_release_gates_unmet',
        tracking_origin='measured_local_run',confidence_config='QCI_3_Severity_IoT/configs/local_research.json',
        mean_alert_latency=memory['core_latency']['mean_ms'],notes=note),'run_id')
    result={'run_id':run_id,'source_commit':commit,**notes}
    (REPORTS/'experiment_tracking.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result))

if __name__=='__main__':main()
