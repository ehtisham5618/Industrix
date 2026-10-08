"""Smoke-check final selected formats on five safety-class calibration images."""
import csv
import json
from pathlib import Path

from .common import ROOT,REPORTS,RUNTIME,digest,source_model,preprocess,write_json,NAMES


def main():
    import cv2
    import numpy as np
    import onnx
    import onnxruntime as ort
    import openvino as ov
    import torch
    from ultralytics.utils.nms import non_max_suppression

    manifest=json.loads((REPORTS/'artifact_manifest.json').read_text())
    for item in manifest['artifacts'].values():assert digest(ROOT/item['path'])==item['sha256']
    import yaml
    dataset=Path(yaml.safe_load((RUNTIME/'evaluation.yaml').read_text())['path'])
    with (REPORTS/'calibration_manifest.csv').open(newline='',encoding='utf-8') as stream:
        rows=list(csv.DictReader(stream))
    selected=[]
    for cls in (7,8,9,10,11):
        row=next(r for r in rows if str(cls) in r['classes'].split(';') and r['image'] not in selected)
        selected.append(row['image'])
    torch.set_num_threads(2)
    model=source_model(ROOT/'Backend/best.pt').model.float().eval().to('cpu')
    graph=onnx.load(str(ROOT/'Backend/weights/onnx_fp16/best_fp16.onnx'));onnx.checker.check_model(graph)
    assert any(item.data_type==onnx.TensorProto.FLOAT16 for item in graph.graph.initializer)
    options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
    session=ort.InferenceSession(str(ROOT/'Backend/weights/onnx_fp16/best_fp16.onnx'),options,providers=['CPUExecutionProvider'])
    compiled=ov.Core().compile_model(str(ROOT/'Backend/weights/openvino_int8/model.xml'),'CPU',{
        'PERFORMANCE_HINT':'LATENCY','NUM_STREAMS':1,'INFERENCE_NUM_THREADS':2})
    results=[]
    with torch.inference_mode():
        for relative in selected:
            tensor=preprocess(cv2.imread(str(dataset/relative)))
            expected=model(torch.from_numpy(tensor))[0].numpy()
            outputs={'onnx_fp16':session.run(None,{session.get_inputs()[0].name:tensor})[0],
                'openvino_int8':compiled([tensor])[compiled.output(0)]}
            row=dict(image=relative,source_shape=list(expected.shape),formats={})
            for name,output in outputs.items():
                assert output.shape==expected.shape==(1,16,8400) and np.isfinite(output).all()
                boxes=non_max_suppression(torch.from_numpy(output.copy()),conf_thres=0.25,iou_thres=0.7,nc=12,max_det=300)[0]
                assert np.isfinite(boxes.numpy()).all()
                assert ((boxes[:,5]>=0)&(boxes[:,5]<12)).all()
                row['formats'][name]=dict(output_shape=list(output.shape),finite=True,
                    max_absolute_delta=float(np.abs(output-expected).max()),
                    mean_absolute_delta=float(np.abs(output-expected).mean()),
                    max_confidence_delta=float(np.abs(output[:,4:]-expected[:,4:]).max()),
                    detected_boxes=len(boxes),detected_classes=[NAMES[int(c)] for c in boxes[:,5]])
            results.append(row)
    write_json(REPORTS/'smoke_validation.json',dict(images=results,onnx_provider=session.get_providers(),
        onnx_checker_pass=True,openvino_execution_devices=compiled.get_property('EXECUTION_DEVICES'),
        selected_artifact_hashes={k:item['sha256'] for k,item in manifest['artifacts'].items()}))
    print('Selected artifact checksums,FP16 graph and five CPU smoke/NMS outputs validated.')


if __name__=='__main__':main()
