"""Generate the report, append-only deployment registry, and existing CME-3 run."""
from __future__ import annotations
import csv
from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
import subprocess

from .common import ROOT,REPORTS,SOURCE_VERSION,DATA_VERSION,NAMES,digest,write_json


def append(path,row,key):
    if path.exists():
        with path.open(encoding='utf-8',newline='') as stream:
            reader=csv.DictReader(stream);fields=reader.fieldnames;records=list(reader)
    else:fields=list(row);records=[]
    normalized={field:str(row.get(field,'')) for field in fields}
    existing=next((r for r in records if r[key]==row[key]),None)
    if existing:
        assert existing==normalized,f'Refusing to overwrite existing history: {row[key]}'
        return
    with path.open('a',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields)
        if not records:writer.writeheader()
        writer.writerow(normalized)


def main():
    path=ROOT/'SED_3_Stress_Testing/reports/quant_report.json'
    report=json.loads(path.read_text())
    tests=json.loads((REPORTS/'test_results.json').read_text())
    artifacts=report['artifacts'];accuracy=report['accuracy'];latency=report['latency']
    source=json.loads((REPORTS/'source_lineage.json').read_text())
    selection=json.loads((REPORTS/'ptq_selection.json').read_text())
    status=report['status']
    calibration=report['calibration']
    environment=report['environment']
    assert artifacts['source_sha256']==digest(ROOT/'Backend/best.pt')
    with (REPORTS/'per_class_comparison.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=['class','fp32_ap50_percent','int8_ap50_percent','delta_pp','onnx_fp16_ap50_percent'])
        writer.writeheader()
        for name in NAMES:
            before=accuracy['fp32']['per_class_ap50'].get(name)
            after=accuracy['int8']['per_class_ap50'].get(name)
            assert before is not None and after is not None,'Do not invent missing class AP'
            writer.writerow(dict(zip(writer.fieldnames,[name,before*100,after*100,(after-before)*100,
                accuracy['onnx_fp16']['per_class_ap50'][name]*100])))
    if not report.get('mlflow_run_id'):
        from Experiment_Tracking.scripts.mlflow_utils import configure_tracking
        mlflow=configure_tracking()
        with mlflow.start_run(run_name='ESE-CPU1: CPU deployment quantization') as run:
            mlflow.set_tags(dict(task='ESE-CPU1',experiment_type='quantization',sprint='Sprint 4',status=status))
            mlflow.log_params(dict(source_model_version=SOURCE_VERSION,dataset_version=DATA_VERSION,
                imgsz=640,batch=1,calibration_count=300,calibration_seed=calibration['seed'],
                cpu=environment['cpu'],calibration_split='train',selected_ptq=selection['selected'],
                **environment['packages']))
            mlflow.log_metrics(dict(fp32_map50=accuracy['fp32']['map50'],int8_map50=accuracy['int8']['map50'],
                map50_drop_pp=accuracy['drop_pp'],int8_size_bytes=artifacts['combined_core_bytes'],
                **{name+'_mean_ms':values['mean_ms'] for name,values in latency.items()}))
            mlflow.log_artifacts(str(REPORTS))
            mlflow.log_artifact(str(path))
            report['mlflow_run_id']=run.info.run_id
        write_json(path,report)
    run_id=report['mlflow_run_id']
    strict=accuracy['strict_0_8pp_pass'];dod=accuracy['dod_1_0pp_pass']
    mode_status='validated_targets_met' if status=='PASS' else 'evaluated_target_shortfall'
    notes=json.dumps(dict(source_sha256=source['checkpoint_sha256'],mlflow_run_id=run_id,
        strict_accuracy_pass=strict,dod_accuracy_pass=dod,size_pass=artifacts['size_pass'],
        latency_pass=report['gates']['latency'],selected_ptq=selection['selected'],
        primary_size_unit='decimal MB;XML+BIN',overall=status),separators=(',',':'))
    for precision,mode,artifact,metrics_key in (
        ('FP16','onnx','Backend/weights/onnx_fp16/best_fp16.onnx','onnx_fp16'),
        ('INT8','openvino','Backend/weights/openvino_int8','int8')):
        backend='onnx_fp16_cpu' if mode=='onnx' else 'openvino_int8_cpu'
        size=artifacts['artifacts']['onnx_fp16']['bytes'] if mode=='onnx' else artifacts['combined_core_bytes']
        measured=accuracy[metrics_key]
        append(ROOT/'Experiment_Tracking/deployment_registry.csv',dict(
            deployment_version=SOURCE_VERSION+'-'+mode+'-'+precision.lower(),source_model_version=SOURCE_VERSION,
            task='ESE-CPU1',precision=precision,runtime='ONNX Runtime' if mode=='onnx' else 'OpenVINO',
            artifact_path=artifact,core_bytes=size,map50=measured['map50'],map50_95=measured['map50_95'],
            map50_drop_pp=(accuracy['fp32']['map50']-measured['map50'])*100,
            cpu_mean_ms=latency[backend]['mean_ms'],cpu_p95_ms=latency[backend]['p95_ms'],
            calibration_count=0 if mode=='onnx' else 300,calibration_seed=calibration['seed'] if mode=='openvino' else '',
            calibration_split='train' if mode=='openvino' else '',artifact_manifest='ESE_CPU1_Quantization/reports/artifact_manifest.json',
            calibration_manifest='ESE_CPU1_Quantization/reports/calibration_manifest.csv' if mode=='openvino' else '',
            benchmark_report='SED_3_Stress_Testing/reports/quant_report.json',status=mode_status,notes=notes),'deployment_version')
    code_commit=subprocess.check_output(['git','log','-1','--format=%H','--','ESE_CPU1_Quantization/export.py'],text=True).strip()
    append(ROOT/'Experiment_Tracking/experiments.csv',dict(run_id='ESECPU1-EXP-001',run_name='ESE-CPU1: CPU quantization',
        sprint='Sprint 4',task='ESE-CPU1',stage='CPU Deployment',experiment_type='quantization',model_version=SOURCE_VERSION,
        model_architecture='YOLOv8s',dataset=source['dataset_yaml'],dataset_version=DATA_VERSION,num_classes=12,
        batch_size=1,imgsz=640,seed=calibration['seed'],device='CPU',environment=environment['cpu'],
        precision=accuracy['int8']['precision'],recall=accuracy['int8']['recall'],map50=accuracy['int8']['map50'],
        map50_95=accuracy['int8']['map50_95'],best_weight_uri='Backend/best.pt',
        exported_weight_uri='Backend/weights/openvino_int8;Backend/weights/onnx_fp16/best_fp16.onnx',
        source_script='Backend/scripts/export_quantized_models.py',git_commit=code_commit or 'uncommitted execution;sealed source checkpoint',
        status=mode_status,tracking_origin='actual_local_cpu_quantization',notes=notes),'run_id')
    lines=['# ESE-CPU1 Quantization Report','',f'**Overall: {status}.**','',
        'Evidence generated: '+datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=5))).isoformat()+'. Original deadline Sep29,2026 was missed; no earlier completion is claimed.','',
        '## Source and lineage','',f"CME-OPT1 `{DATA_VERSION}` -> CME-OPT2 `{SOURCE_VERSION}` -> `Backend/best.pt` -> versioned ONNX FP16/OpenVINO INT8 deployment formats. Architecture YOLOv8s,12classes,{source['parameters']} parameters. Checkpoint SHA256 `{source['checkpoint_sha256']}`. The checkpoint stores compressed floating weights; baseline executes FP32. The trained-model registry and source checkpoint are unchanged. Its previous chemical/smoke target shortfalls remain.",
        f'Class names: {NAMES}. Actual portable YAML: `Hazard_Expansion/configs/12class_data.yaml`, existing augmented_v3 train/val/test paths.','',
        '## Environment','',f'Actual environment: `{environment}`. CPU execution only; no GPU/NPU provider was used. The workstation is shared, not exclusively isolated.','',
        '## Calibration and export','',f"{calibration}. Exactly300 training images,seed{calibration['seed']},greedy inverse-current-class-coverage selection. Byte-identical holdout images are excluded. [Manifest](../../ESE_CPU1_Quantization/reports/calibration_manifest.csv) includes paths,class IDs,andSHA256. Calibration is distinct from val selection and test evaluation.",
        f"PTQ attempts: `{selection}`. Ultralytics 8.4.24 supports int8/half, not quantize8/16. Exactly 300 training paths, fraction1.0, split=train. Actual NNCF activation FakeQuantize ops={artifacts['nncf_fake_quantize_ops']}; constant bytes by precision={artifacts['constant_bytes_by_precision']}. The standard export keeps the upstream detection-head ignored scope and MIXED preset. [NNCF API](https://openvinotoolkit.github.io/nncf/autoapi/nncf/) describes accuracy control. Here the strict held-out shortfall triggered its investigation; validation data alone calibrated the comparison and selected the resulting candidate. Test images never calibrated or ranked scopes.",
        'ONNX FP16 uses CPU FP32 export then onnxconverter-common conversion with FP32 IO; FP16 weights are verified and ONNX checker/CPU session smoke tests execute. CPU provider may promote unsupported half kernels; this does not claim native FP16 CPU arithmetic. See [ORT float16 documentation](https://onnxruntime.ai/docs/performance/model-optimizations/float16.html). Both deployment formats return batch1,16channels,8400candidates (4box+12class scores). Five representative training smoke images and full held-out evaluation validate finite outputs; benchmark NMS validates class IDs.','',
        '## Artifact sizes','', '| Artifact | Bytes | Decimal MB |','|---|---:|---:|',
        f"| PyTorch source checkpoint | {source['source_bytes']} | {source['source_bytes']/1e6:.6f} |"]
    for name,item in artifacts['artifacts'].items():lines.append(f"| {name} | {item['bytes']} | {item['bytes']/1e6:.6f} |")
    lines += [f"| OpenVINO XML+BIN | {artifacts['combined_core_bytes']} | {artifacts['combined_core_decimal_mb']:.6f} |",'',
        f"Primary size gate uses combined XML+BIN <6,500,000bytes: **{'PASS' if artifacts['size_pass'] else 'FAIL'}**. MiB={artifacts['combined_core_mib']:.6f}; runtime metadata is separately counted; complete runtime bytes={artifacts['complete_runtime_bytes']}. No files were deleted to shrink the reported model. Artifact SHA256 values and storage paths are in the manifest. Genuine INT8 of this11.1Mparameter model can exceed6.5MB; no smaller architecture/retraining/int4 substitution is presented as the required model.",'',
        '## Held-out accuracy','',f"Same{report['methodology']['evaluation_images']} test images,labels,and sealed manifest for all formats;imgsz640,batch1,rectFalse,conf0.001,iou0.7,max_det300. CME-2 alert thresholds are not used for mAP. Source baseline is newly evaluated,not copied from old reports.",'',
        '| Metric | PyTorch FP32 | OpenVINO INT8 | INT8 minus FP32 pp | ONNX FP16 |','|---|---:|---:|---:|---:|']
    for key in ('precision','recall','map50','map50_95'):
        values=[f"{accuracy[mode][key]*100:.6f}%" for mode in ('fp32','int8')]
        values += [f"{(accuracy['int8'][key]-accuracy['fp32'][key])*100:.6f}",f"{accuracy['onnx_fp16'][key]*100:.6f}%"]
        lines.append('| '+key+' | '+' | '.join(values)+' |')
    lines += ['',f"mAP50 drop={accuracy['drop_pp']:.6f}percentage points; relative change={accuracy['relative_change_pct']:.6f}%. Strict<0.8pp: **{'PASS' if strict else 'FAIL'}**; automated<1.0pp: **{'PASS' if dod else 'FAIL'}**.",'',
        '| Class | FP32 AP50% | INT8 AP50% | INT8 minus FP32 pp |','|---|---:|---:|---:|']
    for name in NAMES:
        before=accuracy['fp32']['per_class_ap50'][name]*100;after=accuracy['int8']['per_class_ap50'][name]*100
        lines.append(f'| {name} | {before:.6f} | {after:.6f} | {after-before:.6f} |')
    lines += ['', '## CPU latency methodology','',f"Settings: `{report['runtime_settings']}`. Model-only: `{report['methodology']['model_only']}`. End-to-end: `{report['methodology']['end_to_end']}`. Same five held-out input images per runtime;30warmup/200timed calls per category; all samples retained. Compilation is reported separately. Settings/static640x640/batch1/CPU remain identical; no lowered resolution,minimum-only statistic or selected removal of slow runs.",'',
        '| Backend / category | Mean ms | P50 | P90 | P95 | P99 | Min | Max |','|---|---:|---:|---:|---:|---:|---:|---:|']
    for category,values in (('model',latency),('end-to-end',report['end_to_end_latency'])):
        for backend,stats in values.items():
            lines.append('| '+backend+' / '+category+' | '+' | '.join(f'{stats[key]:.6f}' for key in ('mean_ms','p50_ms','p90_ms','p95_ms','p99_ms','min_ms','max_ms'))+' |')
    lines += ['',f"OpenVINO mean model inference<20ms: **{'PASS' if report['gates']['latency'] else 'FAIL'}**. Speedup versus PyTorch={report['speedup_vs_pytorch']:.6f}x. P95 is separately reported. A hardware-specific performance shortfall remains visible; it is not relabeled as full-pipeline latency or throughput.",'',
        '## Tests, tracking and delivery','',f'Test results: `{tests}`. The real saved-metric test is `test_actual_map_drop_below_one_percentage_point`; the real XML+BIN size test is `test_actual_ir_size_below_6_5_decimal_mb`. Functional/runtime failures are never accepted as numeric shortfalls.',
        f"CME-3 experiment `ESECPU1-EXP-001`; actual MLflow run `{run_id}` via the existing helper and `Vision-Driven-Industrial-Safety` experiment name. This offline task creates the local project filesystem store `Experiment_Tracking/mlruns`; historical Modal runs remain unchanged. Source trained-model history stays unchanged; two deployment rows reference `{SOURCE_VERSION}`. Registry files are append-only.",
        'Branch `feature/atlantis-openvino-quant`; exactly two local task commits. Push and PR creation are deferred because organization access was revoked; no PR URL is invented. Run `git push -u origin feature/atlantis-openvino-quant` when permission returns. A verified Git bundle and separate binary archive preserve both source history and artifacts.','',
        '## Deployment recommendation','',
        'Keep the current production default until the measured acceptance gates are met on approved deployment hardware. Generated formats are validated deployment candidates; they do not establish that the source detector meets its previous hazard-class or temporal-recall targets. The current results and all unmet gates are explicit in the checklist.','',
        '[Full acceptance checklist](../../ESE_CPU1_Quantization/reports/Final_Validation_Checklist.md); [artifact manifest](../../ESE_CPU1_Quantization/reports/artifact_manifest.json); [raw latency samples](../../ESE_CPU1_Quantization/reports/latency_samples.csv).','']
    basic_path=REPORTS/'basic_ptq_quant_report.json'
    if basic_path.exists():
        basic=json.loads(basic_path.read_text())
        lines += ['## Preserved basic PTQ attempt','',
            f"Attempt1 basic PTQ test mAP50={basic['accuracy']['int8']['map50']*100:.6f}%, drop={basic['accuracy']['drop_pp']:.6f}pp; core size={basic['artifacts']['combined_core_decimal_mb']:.6f}MB; mean CPU model latency={basic['latency']['openvino_int8_cpu']['mean_ms']:.6f}ms; status={basic['status']}. The complete first result and raw latency samples are retained. The strict test shortfall triggers a validation-only accuracy-control investigation; the test images never calibrate or rank/restores scopes.",
            '[First measured attempt](../../ESE_CPU1_Quantization/reports/basic_ptq_quant_report.json). Current selected result and both validation attempts are reported above. Percentiles use the existing SED-3 nearest-rank convention. No source training,lowered resolution or adjusted acceptance threshold was used.','']
    lines += ['## Review artifacts', '',
        '[Deployment size and CPU latency graph](../../ESE_CPU1_Quantization/reports/cpu_deployment_comparison.png); '
        '[per-class AP change graph](../../ESE_CPU1_Quantization/reports/per_class_quantization_delta.png); '
        '[created/modified/generated file inventory](../../ESE_CPU1_Quantization/reports/file_inventory.json).', '',
        f"OpenVINO runtime node precision tags: `{report.get('openvino_runtime_node_precision_counts')}`. These are node counts, not fractions of execution time. All execution devices are CPU.", '']
    (ROOT/'SED_3_Stress_Testing/reports/ESE_CPU1_Quantization_Report.md').write_text('\n'.join(lines),encoding='utf-8')
    print('Measured report and append-only deployment/CME-3 records generated:',status,run_id)


if __name__=='__main__':main()
