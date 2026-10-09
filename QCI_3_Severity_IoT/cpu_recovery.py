"""Genuine validation-only CPU remediation; never relabel failed size gates."""
from pathlib import Path
import csv
import json
import shutil
import time

ROOT=Path(__file__).resolve().parents[1]
TASK=ROOT/'QCI_3_Severity_IoT'

def main():
    from Backend.offline_policy import configure_local_runtime
    configure_local_runtime()
    import cv2,numpy as np
    cv2.setNumThreads(1);cv2.resize(np.zeros((2,2),np.float32),(3,3))
    import torch,nncf,openvino as ov
    torch.set_num_threads(2)
    from ESE_CPU1_Quantization.common import preprocess,evaluate,digest
    directory=TASK/'runtime/cpu_recovery/full_bias_openvino_model'
    directory.mkdir(parents=True,exist_ok=True)
    with (ROOT/'ESE_CPU1_Quantization/reports/calibration_manifest.csv').open(encoding='utf-8',newline='') as stream:
        rows=list(csv.DictReader(stream))
    assert len(rows)==300 and {r['split'] for r in rows}=={'train'}
    # The manifest stores paths relative to the existing dataset root.
    dataset=ROOT/'Hazard_Expansion/content_runtime/combined_dataset_augmented_v3'
    paths=[dataset/r['image'] for r in rows]
    assert all(p.is_file() for p in paths)
    data=nncf.Dataset(paths,lambda p:preprocess(cv2.imread(str(p))))
    graph=ov.Core().read_model(ROOT/'ESE_CPU1_Quantization/runtime/source_openvino_model/source.xml')
    ignored=nncf.IgnoredScope(patterns=[r'.*model.22/.*/Add',r'.*model.22/.*/Sub*',
        r'.*model.22/.*/Mul*',r'.*model.22/.*/Div*'],types=['Sigmoid'])
    started=time.monotonic()
    candidate=nncf.quantize(graph,data,subset_size=300,preset=nncf.QuantizationPreset.MIXED,
        ignored_scope=ignored,target_device=nncf.TargetDevice.CPU,fast_bias_correction=False)
    ov.save_model(candidate,directory/'model.xml',compress_to_fp16=False)
    shutil.copy2(ROOT/'Backend/weights/openvino_int8/metadata.yaml',directory/'metadata.yaml')
    validation=evaluate(directory/'model.xml',ROOT/'ESE_CPU1_Quantization/runtime/evaluation.yaml','qci3_full_bias_validation',split='val')
    existing=json.loads((ROOT/'ESE_CPU1_Quantization/reports/accuracy_aware_validation_metrics.json').read_text())
    result={'method':'full_bias_correction','training_calibration_samples':300,'selection_split':'val',
        'candidate_validation':validation,'existing_validation':existing,'elapsed_seconds':time.monotonic()-started,
        'candidate_xml_sha256':digest(directory/'model.xml'),'candidate_bin_sha256':digest(directory/'model.bin'),
        'candidate_core_bytes':sum((directory/n).stat().st_size for n in ('model.xml','model.bin')),
        'selected':validation['map50']>existing['map50'],'deployed':False,'test_used_for_selection':False}
    out=ROOT/'reports/qci3/cpu_bias_candidate.json';out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result),flush=True)

if __name__=='__main__':main()
