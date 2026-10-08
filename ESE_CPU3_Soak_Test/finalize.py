"""Attach measured one-hour evidence to the existing local CME-3 experiment store."""
import csv
import io
import json
import re
import subprocess

from ESE_CPU1_Quantization.common import ROOT,digest,write_json


def test_result(name):
    path=ROOT/'ESE_CPU3_Soak_Test/reports'/name
    text=path.read_text()
    count=int(re.search(r'Ran (\d+) tests',text)[1])
    return dict(file=path.relative_to(ROOT).as_posix(),tests=count,
        passed=count if '\nOK\n' in text and 'Exit code: 0' in text else 0)


def main():
    report_path=ROOT/'SED_3_Stress_Testing/reports/cpu_soak_report.json'
    report=json.loads(report_path.read_text())
    if report['status']!='completed' or report['duration_actual_seconds']<3600:
        raise RuntimeError('Final tracking/commit evidence requires a genuine completed one-hour run')
    source_commit=subprocess.check_output(['git','log','-1','--format=%H','--','SED_3_Stress_Testing/scripts/soak_test.py'],cwd=ROOT,text=True).strip()
    tests={key:test_result(name) for key,name in [
        ('sed1','updated_sed1_tests_terminal.txt'),('sed2','existing_sed2_tests_terminal.txt'),('sed3','combined_sed3_tests_terminal.txt')]}
    if any(t['tests']!=t['passed'] for t in tests.values()):raise RuntimeError('Required related test failure')
    report['tests']=tests;report['source_commit']=source_commit
    from Experiment_Tracking.scripts.mlflow_utils import configure_tracking
    mlflow=configure_tracking(ROOT/'Experiment_Tracking/mlruns')
    with mlflow.start_run(run_name='ESE-CPU3: one-hour OpenVINO CPU soak') as run:
        mlflow.set_tags(dict(task='ESE-CPU3',experiment_type='cpu_soak_test',sprint='Sprint 4',
            status=report['overall'],execution_status=report['status'],config_version=report['config_version']))
        mlflow.log_params(dict(duration=3600,engine='openvino',streams=3,model_version=report['model_version'],
            ingestion_config_version=report['ingestion_config_version'],sampling_ratio='1/4',
            cpu=report['hardware']['cpu'],openvino_version=report['hardware']['openvino'],
            cpu_threads=report['engine_verification']['settings']['threads'],warmup=report['warmup_seconds'],
            source_commit=source_commit,model_xml_sha256=report['engine_verification']['artifact_manifest']['artifacts']['openvino_xml']['sha256']))
        metrics=dict(operational_fps=report['throughput']['operational_mean_fps'],
            inference_capacity_fps=report['throughput']['inference_capacity_fps_if_measured'],
            mean_latency=report['latency']['mean_ms'],p95_latency=report['latency']['p95_ms'],
            mean_cpu=report['cpu']['system_mean_pct'],peak_cpu=report['cpu']['system_peak_pct'],
            process_cpu=report['cpu']['process_mean_pct'],rss_start=report['memory']['rss_start_mb'],
            rss_peak=report['memory']['rss_peak_mb'],rss_end=report['memory']['rss_end_mb'],
            rss_slope=report['memory']['rss_slope_mb_per_hour'],python_alloc_peak=report['memory']['tracemalloc_peak_mb'],
            temperature_peak=report['thermal']['peak_temp_c'],frequency_min=report['thermal']['min_freq_mhz'],
            crash_count=report['streams_health']['crashes'],buffer_overruns=report['streams_health']['buffer_overruns'],
            actual_duration=report['duration_actual_seconds'])
        mlflow.log_metrics({k:v for k,v in metrics.items() if v is not None})
        report['mlflow_run_id']=run.info.run_id
        report['acceptance']['CME-3 tracking updated']='PASS'
        write_json(report_path,report)
        markdown=report_path.parent/'ESE_CPU3_Soak_Test_Report.md'
        text=markdown.read_text().replace('| CME-3 tracking updated | PENDING until offline finalization |',
                                         '| CME-3 tracking updated | PASS |')
        text += '\nCME-3 local MLflow run `'+run.info.run_id+'`, source commit `'+source_commit+'`.\n'
        text += '\nRelated tests: `'+json.dumps(tests)+'`; all '+str(sum(t['tests'] for t in tests.values()))+' passed.\n'
        markdown.write_text(text)
        for path in report_path.parent.glob('cpu_soak*'):
            if path.is_file():mlflow.log_artifact(str(path))
        mlflow.log_artifact(str(markdown))
        mlflow.log_artifacts(str(ROOT/'ESE_CPU3_Soak_Test/reports'))
    registry=ROOT/'Experiment_Tracking/experiments.csv'
    original=registry.read_bytes();rows=list(csv.DictReader(io.StringIO(original.decode())))
    if any(r['run_id']=='ESECPU3-EXP-001' for r in rows):raise RuntimeError('CPU3 registry row already exists')
    row=dict(run_id='ESECPU3-EXP-001',run_name='ESE-CPU3: one-hour OpenVINO CPU soak',sprint='Sprint 4',
        task='ESE-CPU3',stage='CPU Soak',experiment_type='cpu_soak_test',model_version=report['model_version'],
        alert_policy_version='cmeopt3-bytetrack15-v1',model_architecture='YOLOv8s',num_classes=12,
        batch_size=1,imgsz=640,device='CPU',environment=report['hardware']['cpu'],
        best_weight_uri='Backend/best.pt',exported_weight_uri='Backend/weights/openvino_int8',
        source_script='SED_3_Stress_Testing/scripts/soak_test.py',git_commit=source_commit,
        status='validated_targets_met' if report['overall']=='PASS' else 'evaluated_target_shortfall',
        tracking_origin='actual_local_cpu_soak',confidence_config='Confidence_Calibration/configs/calibrated_thresholds.yaml',
        sampling_fps=json.dumps({c:s['operational_fps'] for c,s in report['stream_results'].items()}),
        window_size=15,required_frames=15,
        notes=json.dumps(dict(mlflow_run_id=report['mlflow_run_id'],config_version=report['config_version'],
            duration=report['duration_actual_seconds'],overall=report['overall'],
            operational_fps=report['throughput']['operational_mean_fps'],
            capacity_fps=report['throughput']['inference_capacity_fps_if_measured'],
            memory_leak=report['memory']['leak_detected'],thermal=report['thermal']['throttling_evidence'],
            report='SED_3_Stress_Testing/reports/cpu_soak_report.json'),separators=(',',':')))
    buffer=io.StringIO(newline='');writer=csv.DictWriter(buffer,fieldnames=list(rows[0]));writer.writerow({k:row.get(k,'') for k in rows[0]})
    registry.write_bytes(original+buffer.getvalue().encode())
    print(json.dumps(dict(mlflow_run_id=report['mlflow_run_id'],tests=tests,status=report['overall']),indent=2))


if __name__=='__main__':main()
