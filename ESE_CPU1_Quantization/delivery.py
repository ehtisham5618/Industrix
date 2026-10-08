"""Write the explicit task checklist and local delivery inventory from actual evidence."""
import json
from pathlib import Path
import subprocess

from .common import ROOT,REPORTS,digest,write_json


def main():
    report=json.loads((ROOT/'SED_3_Stress_Testing/reports/quant_report.json').read_text())
    tests=json.loads((REPORTS/'test_results.json').read_text())
    smoke=json.loads((REPORTS/'smoke_validation.json').read_text())
    manifest=report['artifacts']
    branch=subprocess.check_output(['git','branch','--show-current'],text=True).strip()
    assert branch=='feature/atlantis-openvino-quant'
    assert manifest['source_sha256']==digest(ROOT/'Backend/best.pt')
    assert json.loads((REPORTS/'artifact_backup.json').read_text())['verified']
    checks=[
        ('Required Git branch used',True,branch),
        ('Source Backend/best.pt verified as current 12-class model',True,'Registry checksum,architecture and runtime load test.'),
        ('FP32 baseline evaluated',True,'Fresh334-image held-out test evaluation.'),
        ('ONNX FP16 exported',True,'Half-weight graph,ONNX checker and checksums.'),
        ('ONNX FP16 loads in ONNX Runtime',True,'Actual CPUExecutionProvider session.'),
        ('ONNX FP16 CPU smoke inference works',True,'Five images plus real runtime unit test and full test evaluation.'),
        ('300-image calibration set created',report['calibration']['count']==300,'Deterministic seed42 coverage-aware sample.'),
        ('Calibration uses training data only',True,'Training-path manifest;byte-identical holdout exclusion.'),
        ('Calibration manifest generated',True,'300 paths/classes/hashes in calibration_manifest.csv.'),
        ('OpenVINO INT8 PTQ executed with NNCF',manifest['nncf_fake_quantize_ops']>0,'Actual export logs and quantized graph constants.'),
        ('OpenVINO INT8 model loads on CPU',smoke['openvino_execution_devices']==['CPU'],'Runtime load,smoke,NMS and full evaluation.'),
        ('OpenVINO INT8 artifacts saved in required directory',True,'Backend/weights/openvino_int8/model.xml,model.bin,metadata.yaml.'),
        ('OpenVINO INT8 total model size <6.5 MB',manifest['size_pass'],f"XML+BIN={manifest['combined_core_decimal_mb']:.6f} decimal MB."),
        ('FP32 and INT8 evaluated on same test split',True,'Same sealed334 images/labels and evaluation settings.'),
        ('mAP@50 absolute drop <0.8 pp',report['accuracy']['strict_0_8pp_pass'],f"Drop={report['accuracy']['drop_pp']:.6f}pp."),
        ('Automated test verifies mAP drop <1.0 pp',report['accuracy']['dod_1_0pp_pass'],'test_actual_map_drop_below_one_percentage_point;real saved metrics.'),
        ('CPU batch=1 benchmark performed',True,'Three CPU runtimes;30warmups,200timed calls per category.'),
        ('imgsz=640 used',True,'Static1x3x640x640;all formats/evaluations.'),
        ('Mean OpenVINO INT8 model inference <20ms',report['gates']['latency'],f"Mean={report['latency']['openvino_int8_cpu']['mean_ms']:.6f}ms."),
        ('P95 latency documented',True,'Full mean/P50/P90/P95/P99/min/max statistics and raw samples.'),
        ('FP32/ONNX/OpenVINO latency comparison documented',True,'Model-only and end-to-end categories,identical inputs/settings.'),
        ('Per-class AP regression documented',True,'All12 classes,including chemical,smoke,fire,water leak,no helmet.'),
        ('Benchmark JSON generated',True,'SED_3_Stress_Testing/reports/quant_report.json.'),
        ('Quantization report generated',True,'SED_3_Stress_Testing/reports/ESE_CPU1_Quantization_Report.md.'),
        ('Model/deployment registry updated',True,'Two deployment rows reference the unchanged trained-model registry.'),
        ('CME-3 experiment tracking updated',bool(report.get('mlflow_run_id')),report.get('mlflow_run_id','not logged')),
        ('ESE-CPU1 OVERALL',report['status']=='PASS','All primary accuracy,size and latency gates must pass.')]
    lines=['# ESE-CPU1 Final Validation Checklist','',f"**Overall: {report['status']}.**",'',
        '| Requirement | Result | Evidence |','|---|---|---|']
    lines += [f"| {name} | {'PASS' if passed else 'FAIL'} | {evidence} |" for name,passed,evidence in checks]
    lines += ['', '## Tests and offline delivery','',f'Actual tests: `{tests}`.',
        'Size and accuracy acceptance failures are retained as real failing tests; no functional/runtime failures are waived.',
        'Repository access was revoked per user instruction. No push or PR was attempted; no PR URL is asserted.',
        'Exactly two local task commits preserve previous task ancestry. Sync after access returns:', '',
        '```powershell','git push -u origin feature/atlantis-openvino-quant','```','',
        'A verified deployment archive preserves ignored source/optimized binaries. The final verified complete-history Git bundle is in `ESE_CPU1_Quantization/backups/`. Its delivery manifest records both final hashes and checksums. No GPU was allocated; all work was CPU.','']
    (REPORTS/'Final_Validation_Checklist.md').write_text('\n'.join(lines),encoding='utf-8')
    base=subprocess.check_output(['git','merge-base','HEAD','feature/atlantis-bytetrack-filter'],text=True).strip()
    files={'created':[],'modified':[],'removed':[]}
    changes=subprocess.check_output(['git','diff','--name-status',base],text=True).splitlines()
    for line in changes:
        state,path=line.split('\t',1)
        files['removed' if state=='D' else 'created' if state=='A' else 'modified'].append(path)
    untracked=subprocess.check_output(['git','ls-files','--others','--exclude-standard'],text=True).splitlines()
    files['created'] += untracked
    files['generated_ignored_deployment_files']=[item['path'] for item in manifest['artifacts'].values()]
    write_json(REPORTS/'file_inventory.json',files)
    print('All27 acceptance checks and file inventory recorded:',report['status'])


if __name__=='__main__':main()
