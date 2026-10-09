"""Record measured reporting results using the existing local MLflow/CSV registry."""
import csv
import json
from pathlib import Path
import subprocess
from QCI_3_Severity_IoT.offline import loopback_only
ROOT=Path(__file__).resolve().parents[1];REPORTS=ROOT/'reports/qci5'

def main():
    from Backend.offline_policy import configure_local_runtime
    configure_local_runtime()
    from Experiment_Tracking.scripts.mlflow_utils import configure_tracking
    demo=json.loads((REPORTS/'pdf_demo.json').read_text());memory=json.loads((REPORTS/'memory_profile.json').read_text())
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    notes=dict(report_version='qci5-report-v1',QCI2_model_version=demo['lineage']['model_version'],
        QCI3_policy_version=demo['lineage']['policy_version'],QCI4_policy_version='qci4-edge-policy-v1',
        source_commit=commit,sample_event_digest=demo['lineage']['event_digest'],
        memory_drift_percent=memory['matched_window_drift_percent'],external_socket_attempts=0,
        local_feature_acceptance='PASS',full_repository_cpu_acceptance='FAIL',github_delivery='DEFERRED_USER_LOCAL_ONLY')
    with loopback_only():
        mlflow=configure_tracking(ROOT/'Experiment_Tracking/mlruns')
        with mlflow.start_run(run_name='QCI-5 local incident PDF export and download') as run:
            mlflow.set_tags({'task':'QCI-5','sprint':'Sprint 2','implementation':'PASS','overall_dod':'FAIL','sample_scope':'existing_QCI3_research_demo'})
            mlflow.log_params(notes)
            mlflow.log_metrics({'memory_drift_percent':memory['matched_window_drift_percent'],
                'pdf_mean_ms':memory['timings']['latency_ms']['mean_ms'],'pdf_p95_ms':memory['timings']['latency_ms']['p95_ms'],
                'sample_pdf_bytes':demo['sample_export']['size_bytes'],'profile_exports':memory['exports']})
            for name in ('pdf_demo.json','memory_profile.json','pytest_output.txt','sample_incident_report.pdf'):
                mlflow.log_artifact(str(REPORTS/name))
            run_id=run.info.run_id
    path=ROOT/'Experiment_Tracking/experiments.csv'
    with path.open(encoding='utf-8',newline='') as stream:
        reader=csv.DictReader(stream);fields=reader.fieldnames
        if any(r['task']=='QCI-5' for r in reader):raise ValueError('QCI-5 already recorded; duplicate refused')
    row=dict(run_id=run_id,run_name='QCI-5 local incident PDF export and download',sprint='Sprint 2',task='QCI-5',stage='Local incident reporting',
        experiment_type='local_incident_pdf',model_version=demo['lineage']['model_version'],alert_policy_version=demo['lineage']['policy_version'],
        model_architecture='QCI-2/QCI-3 stored result consumer',num_classes=2,device='cpu',source_script='QCI_5_Incident_PDF/verify.py',git_commit=commit,
        status='local_feature_verified_inherited_cpu_release_gates_unmet',tracking_origin='measured_local_run',
        confidence_config='QCI_5_Incident_PDF/configs/local_safe.json',notes=json.dumps(notes,separators=(',',':')))
    with path.open('a',encoding='utf-8',newline='') as stream:csv.DictWriter(stream,fieldnames=fields).writerow({f:row.get(f,'') for f in fields})
    (REPORTS/'experiment_tracking.json').write_text(json.dumps(dict(run_id=run_id,**notes),indent=2)+'\n',encoding='utf-8')
    print(run_id)
if __name__=='__main__':main()
