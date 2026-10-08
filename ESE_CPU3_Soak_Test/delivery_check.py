"""Validate the one-hour claim against raw persisted telemetry and model lineage."""
import csv
import hashlib
import json
import subprocess

from ESE_CPU1_Quantization.common import ROOT,digest,write_json
from .report import read_rows

BASE='79a1d8cff0a95f6b2d1e0014c36dd60a4752c018'


def main():
    report=json.loads((ROOT/'SED_3_Stress_Testing/reports/cpu_soak_report.json').read_text())
    rows=read_rows(ROOT/report['telemetry_path'])
    measured=[r for r in rows if not r['warmup']]
    frames=read_rows(ROOT/report['frame_timings_path'])
    primary=[r for r in frames if report['warmup_seconds']<=r['elapsed_seconds']<=report['capture_wall_seconds']]
    original_csv=subprocess.check_output(['git','show',BASE+':Experiment_Tracking/experiments.csv'],cwd=ROOT)
    current_csv=(ROOT/'Experiment_Tracking/experiments.csv').read_bytes()
    manifest=report['engine_verification']['artifact_manifest']
    def preserved_run_source(name,sha):
        if digest(ROOT/name)==sha:return True
        # The first commit preserves the exact measured harness. The evidence
        # commit may add non-runtime CLI input normalization after the run.
        original=subprocess.check_output(['git','show',report['source_commit']+':'+name],cwd=ROOT)
        return hashlib.sha256(original).hexdigest()==sha
    checks=dict(
        actual_continuous_3600_seconds=report['status']=='completed' and report['duration_actual_seconds']>=3600,
        telemetry_covers_full_requested_window=max(r['soak_elapsed_seconds'] for r in measured)>=3600,
        six_ten_minute_windows=len(report['windows'])==6,
        no_telemetry_gap=max(r['sample_interval_seconds'] for r in rows)<15,
        three_capture_workers_active_after_warmup=all(r['capture_thread_count']==3 and r['active_streams']==3 for r in measured),
        selected_int8_artifact_unchanged=all(digest(ROOT/item['path'])==item['sha256'] for key,item in manifest['artifacts'].items()
            if key in ('openvino_xml','openvino_bin','metadata')),
        source_checkpoint_unchanged=digest(ROOT/'Backend/best.pt')==manifest['source_sha256'],
        cpu_only_execution=report['engine_verification']['execution_devices']==['CPU'],
        actual_int8_runtime_ops=any(k in ('i8','u8') for k in report['engine_verification']['runtime_precision_counts']),
        no_silent_backend_fallback=report['engine']=='openvino',
        raw_timing_agrees_with_operational_fps=abs(len(primary)/report['duration_actual_seconds']-report['throughput']['operational_mean_fps'])<1e-9,
        captured_and_selected_frame_conservation=all(m['captured']==m['selected']+m['intentional_skips'] and
            m['selected']==m['evaluated']+m['ring']['true_overruns']+m['inference_drops']+m['ring']['pending_selected']
            for m in report['manager_metrics'].values()),
        rings_never_exceed_fifteen=all(m['ring']['max_occupancy']<=15 for m in report['manager_metrics'].values()),
        no_orphan_capture_scheduler=not report['threads_after_shutdown'] and not report['scheduler_after_shutdown'],
        measured_run_code_preserved_in_source_commit=all(preserved_run_source(name,sha) for name,sha in report['code_file_hashes'].items()),
        trained_model_and_alert_policy_registry_unchanged=not subprocess.check_output(['git','diff',BASE,'--',
            'Experiment_Tracking/model_registry.csv','Experiment_Tracking/alert_policy_registry.csv'],cwd=ROOT).strip(),
        original_experiment_history_preserved=current_csv.replace(b'\r\n',b'\n').startswith(original_csv.replace(b'\r\n',b'\n')),
        exactly_one_cpu3_experiment_appended=current_csv.decode().count('ESECPU3-EXP-001')==1,
        mlflow_run_exists=any((ROOT/'Experiment_Tracking/mlruns').glob('*/'+report['mlflow_run_id']+'/meta.yaml')),
        missing_temperature_not_fabricated=report['thermal']['temperature_available'] or report['thermal']['peak_temp_c'] is None,
        throughput_target_not_redefined=report['dod']['throughput_target_met']==(report['throughput']['operational_mean_fps']>=45),
        both_throughputs_labeled=report['throughput']['inference_capacity_fps_if_measured'] is not None,
        actual_graphs_generated=all((ROOT/'SED_3_Stress_Testing/reports'/('cpu_soak_'+name+'.png')).exists()
                                  for name in ('cpu','memory','fps','thermal')),
        tests_all_pass=all(t['passed']==t['tests'] for t in report['tests'].values()),
    )
    record=dict(status='PASS' if all(checks.values()) else 'FAIL',checks=checks,
        actual_run_status=report['status'],measured_acceptance=report['overall'],
        base_commit=BASE,source_commit=report['source_commit'],
        task_branch='feature/atlantis-cpu-soak-test',expected_new_task_commits=2,
        push_status='Deferred: user reports revoked organization access',pr_created=False)
    write_json(ROOT/'ESE_CPU3_Soak_Test/reports/delivery_validation.json',record)
    print(json.dumps(record,indent=2))
    if record['status']!='PASS':raise SystemExit(1)


if __name__=='__main__':main()
