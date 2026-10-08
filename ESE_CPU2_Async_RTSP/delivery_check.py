"""Verify measured source lineage, frame accounting and offline handoff inputs."""
import hashlib
import json
import subprocess

from .benchmark import ROOT,REPORTS,digest,write_json


def main():
    baseline=json.loads((REPORTS/'baseline_metrics.json').read_text())
    optimized=json.loads((REPORTS/'optimized_metrics.json').read_text())
    summary=json.loads((REPORTS/'acceptance_summary.json').read_text())
    base=baseline['git_head']
    original_csv=subprocess.check_output(['git','show',base+':Experiment_Tracking/experiments.csv'],cwd=ROOT)
    current_csv=(ROOT/'Experiment_Tracking/experiments.csv').read_bytes()
    source_path='SED_1_Multi_Camera/scripts/stream_manager.py'
    original_source=subprocess.check_output(['git','show',base+':'+source_path],cwd=ROOT)
    checks=dict(
        source_checkpoint_unchanged=digest(ROOT/'Backend/best.pt')==baseline['environment']['model_sha256']==optimized['environment']['model_sha256'],
        measured_manager_still_current=digest(ROOT/source_path)==optimized['manager_source_sha256'],
        baseline_git_head_matches_saved_task_base=base=='f239c770dfdaea862b4e108f3dacd3abc8c72484',
        measured_original_working_file_hash_recorded=len(baseline['manager_source_sha256'])==64,
        baseline_and_optimized_each_180_seconds=min(baseline['capture_duration_seconds'],optimized['capture_duration_seconds'])>=180,
        identical_detector_settings=all(baseline['environment'][k]==optimized['environment'][k]
            for k in ('model_sha256','precision','imgsz','torch_threads','cv_threads','micro_batch')),
        identical_input_hashes_and_native_geometry=all(baseline['streams'][c]['source']==s['source'] for c,s in optimized['streams'].items()),
        original_experiment_csv_prefix_preserved_after_git_lineending_normalization=current_csv.replace(b'\r\n',b'\n').startswith(original_csv.replace(b'\r\n',b'\n')),
        exactly_one_ingestion_experiment_appended=current_csv[len(original_csv):].decode().count('ESECPU2-EXP-001')==1,
        prior_trained_model_and_policy_history_unchanged=not subprocess.check_output(['git','diff',base,'--',
            'Experiment_Tracking/model_registry.csv','Experiment_Tracking/alert_policy_registry.csv'],cwd=ROOT).strip(),
        no_orphan_workers=not optimized['live_threads_after_stop'] and not optimized['scheduler_alive_after_stop'],
        intentional_skip_and_selected_loss_conservation=all(s['captured']==s['intentional_skips']+s['selected_for_evaluation'] and
            s['selected_for_evaluation']==s['evaluated']+s['counters']['buffer']['true_overruns']+s['counters']['inference_drops']
            for s in optimized['streams'].values()),
        rings_never_exceed_fifteen=all(s['counters']['buffer']['max_occupancy']<=15 for s in optimized['streams'].values()),
        required_tests_all_pass=summary['tests']['required']['status']=='PASS',
        actual_mlflow_run_present=any((ROOT/'Experiment_Tracking/mlruns').glob('*/'+summary['mlflow_run_id']+'/meta.yaml')),
        no_false_acceptance_pass=summary['status']==optimized['status']=='FAIL',
        recovery_helper_present=(ROOT/'ESE_CPU2_Async_RTSP/offline_backup.py').exists(),
        sync_command_normal_push=(ROOT/'ESE_CPU2_Async_RTSP/sync_when_access_returns.ps1').exists(),
    )
    result=dict(status='PASS' if all(checks.values()) else 'FAIL',checks=checks,
        measured_acceptance=summary['status'],source_commit=summary['source_commit'],
        task_branch='feature/atlantis-async-rtsp',expected_new_task_commits=2,
        task_base_commit=base,push_status='Deferred: user reports organization access revoked',
        pr_created=False,source_checkpoint_sha256=optimized['environment']['model_sha256'],
        baseline_original_git_blob_sha256=hashlib.sha256(original_source).hexdigest(),
        baseline_measured_windows_working_file_sha256=baseline['manager_source_sha256'],
        source_provenance='Baseline ran before manager edits and git status was clean. Working-file hash and saved Git-blob hash are separate byte identities; Git normalizes line endings.')
    write_json(REPORTS/'delivery_validation.json',result)
    print(json.dumps(result,indent=2))
    if result['status']!='PASS':raise SystemExit(1)


if __name__=='__main__':main()
