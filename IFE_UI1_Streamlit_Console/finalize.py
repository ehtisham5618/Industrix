"""Publish measured UI evidence to the existing local CME-3 experiment store."""
import csv
import io
import json
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def main():
    path=ROOT/'Frontend/reports/ife_ui1_metrics.json';report=json.loads(path.read_text())
    if report['status']!='completed' or report['duration_actual_seconds']<180:
        raise RuntimeError('Final evidence requires an actual completed 180-second UI integration run')
    tests=json.loads((ROOT/'IFE_UI1_Streamlit_Console/reports/test_results.json').read_text())
    if not all(v['passed'] for v in tests.values()):raise RuntimeError('Required test/registry failure')
    source_commit=subprocess.check_output(['git','log','-1','--format=%H','--','Frontend/app.py'],cwd=ROOT,text=True).strip()
    report['source_commit']=source_commit;report['tests']=tests
    from Experiment_Tracking.scripts.mlflow_utils import configure_tracking
    mlflow=configure_tracking(ROOT/'Experiment_Tracking/mlruns')
    with mlflow.start_run(run_name='IFE-UI1: three-camera Streamlit console integration') as run:
        mlflow.set_tags(dict(task='IFE-UI1',experiment_type='frontend_integration',sprint='Sprint 4',
            config_version=report['config_version'],status=report['overall']))
        mlflow.log_params(dict(duration=180,engine='OpenVINO INT8 CPU',streams=3,
            model_version=report['model_version'],sampling_ratio='1/4',source_commit=source_commit,
            inference_threads=2,browser=report['browser']))
        mlflow.log_metrics(dict(mean_ui_delivery_ms=report['delivery_latency_ms']['mean'],
            p95_ui_delivery_ms=report['delivery_latency_ms']['p95'],
            max_ui_delivery_ms=report['delivery_latency_ms']['max'],
            aggregate_ui_update_fps=report['aggregate_ui_update_fps'],
            mean_capture_to_canvas_ms=report['capture_to_canvas_ms']['mean'],
            mean_system_cpu=report['telemetry']['system_cpu_percent']['mean'],
            mean_backend_rss_mib=report['telemetry']['backend_rss_mib']['mean'],
            actual_duration_seconds=report['duration_actual_seconds']))
        report['mlflow_run_id']=run.info.run_id
        path.write_text(json.dumps(report,indent=2),encoding='utf-8')
        from IFE_UI1_Streamlit_Console.report import render_report
        render_report(report)
        mlflow.log_artifacts(str(path.parent));mlflow.log_artifacts(str(ROOT/'IFE_UI1_Streamlit_Console/reports'))
    registry=ROOT/'Experiment_Tracking/experiments.csv';original=registry.read_bytes()
    rows=list(csv.DictReader(io.StringIO(original.decode())))
    if any(r['run_id']=='IFEUI1-EXP-001' for r in rows):raise RuntimeError('UI1 registry row already exists')
    row=dict(run_id='IFEUI1-EXP-001',run_name='IFE-UI1: three-camera Streamlit console integration',sprint='Sprint 4',
        task='IFE-UI1',stage='Frontend Integration',experiment_type='frontend_integration',
        model_version=report['model_version'],alert_policy_version='cmeopt3-bytetrack15-v1',
        model_architecture='YOLOv8s',num_classes=12,batch_size=1,imgsz=640,device='CPU',
        environment=report['hardware']['cpu'],best_weight_uri='Backend/best.pt',
        exported_weight_uri='Backend/weights/openvino_int8',source_script='IFE_UI1_Streamlit_Console/benchmark.py',
        git_commit=source_commit,status='validated_targets_met' if report['overall']=='PASS' else 'evaluated_target_shortfall',
        tracking_origin='actual_local_frontend_integration',confidence_config='Confidence_Calibration/configs/calibrated_thresholds.yaml',
        sampling_fps=json.dumps(report['per_camera_update_fps']),window_size=15,required_frames=15,
        notes=json.dumps(dict(mlflow_run_id=report['mlflow_run_id'],config_version=report['config_version'],
            overall=report['overall'],mean_ui_ms=report['delivery_latency_ms']['mean'],
            p95_ui_ms=report['delivery_latency_ms']['p95'],duration=report['duration_actual_seconds'],
            report='Frontend/reports/ife_ui1_metrics.json'),separators=(',',':')))
    buffer=io.StringIO(newline='');writer=csv.DictWriter(buffer,fieldnames=list(rows[0]));writer.writerow({k:row.get(k,'') for k in rows[0]})
    registry.write_bytes(original+buffer.getvalue().encode())
    print(json.dumps(dict(mlflow_run_id=report['mlflow_run_id'],source_commit=source_commit,status=report['overall']),indent=2))

if __name__=='__main__':main()
