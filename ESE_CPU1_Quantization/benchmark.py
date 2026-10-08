from __future__ import annotations
import csv
import json
import math
import time
from pathlib import Path

from .common import (ROOT,REPORTS,RUNTIME,SOURCE_VERSION,DATA_VERSION,digest,source_model,
    dataset_config,environment,write_json,preprocess,evaluate,accuracy_delta)
from SED_3_Stress_Testing.scripts.analysis import summarize_values,percentile


def latency_summary(samples,warmup,threads):
    if not samples or any(not math.isfinite(value) or value<=0 for value in samples):
        raise ValueError('Latency must contain real positive measurements')
    base=summarize_values(samples)
    return dict(**{k+'_ms':v for k,v in base.items()},p90_ms=percentile(samples,90),
        iterations=len(samples),warmup_iterations=warmup,batch=1,imgsz=640,device='CPU',threads=threads)


def run(args):
    import cv2
    import numpy as np
    import onnxruntime as ort
    import openvino as ov
    import torch
    from ultralytics.utils.nms import non_max_suppression

    profile_path=REPORTS/'cpu_thread_profile.json'
    profile=json.loads(profile_path.read_text()) if profile_path.exists() else None
    if args.threads is None:
        args.threads=profile['selected_threads'] if profile else 2
    if profile:
        assert profile['xml_sha256']==digest(args.output_root/'openvino_int8/model.xml')
        assert profile['bin_sha256']==digest(args.output_root/'openvino_int8/model.bin')
    if args.iterations<200 or args.warmup<20 or args.threads<1:
        raise ValueError('Official benchmark requires >=200 iterations,>=20 warmup,positive threads')
    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(1)
    model=source_model(args.weights)
    config,data=dataset_config(args.data)
    manifest=json.loads((REPORTS/'artifact_manifest.json').read_text())
    for item in manifest['artifacts'].values():
        assert digest(ROOT/item['path'])==item['sha256'], 'Deployment artifact has changed'
    assert manifest['source_sha256']==digest(args.weights)
    files=sorted(p for p in (Path(config['path'])/config['test']).glob('*') if p.suffix.lower() in ('.png','.jpeg','.jpg'))
    assert files
    # Sealed same334 image/label bytes across evaluations, including images that have no predictions.
    test_fingerprint={p.relative_to(Path(config['path'])).as_posix():digest(p) for p in files}
    for p in sorted((Path(config['path'])/'labels/test').glob('*.txt')):
        test_fingerprint[p.relative_to(Path(config['path'])).as_posix()]=digest(p)
    write_json(REPORTS/'test_split_manifest.json',test_fingerprint)
    fp16_path=args.output_root/'onnx_fp16/best_fp16.onnx'
    int8_path=args.output_root/'openvino_int8/model.xml'
    if not args.skip_evaluation:
        fp32=evaluate(args.weights,data,'fp32')
        fp32['checkpoint_sha256']=digest(args.weights)
        write_json(REPORTS/'fp32_metrics.json',fp32)
        int8=evaluate(int8_path,data,'int8')
        fp16=evaluate(fp16_path,data,'onnx_fp16')
    else:
        fp32=json.loads((REPORTS/'fp32_metrics.json').read_text())
        int8=json.loads((REPORTS/'int8_metrics.json').read_text())
        fp16=json.loads((REPORTS/'onnx_fp16_metrics.json').read_text())
        assert fp32['checkpoint_sha256']==digest(args.weights)
        assert int8['artifact_sha256']==digest(int8_path)
        assert int8['artifact_bin_sha256']==digest(int8_path.with_suffix('.bin'))
        assert fp16['artifact_sha256']==digest(fp16_path)
    for p in files:
        assert digest(p)==test_fingerprint[p.relative_to(Path(config['path'])).as_posix()]
    torch.set_num_threads(args.threads)
    model.model.fuse().to('cpu').float().eval()
    assert all(p.device.type=='cpu' for p in model.model.parameters())
    options=ort.SessionOptions();options.intra_op_num_threads=args.threads;options.inter_op_num_threads=1
    options.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
    session=ort.InferenceSession(str(fp16_path),options,providers=['CPUExecutionProvider'])
    assert session.get_providers()==['CPUExecutionProvider']
    core=ov.Core()
    started=time.perf_counter()
    compiled=core.compile_model(str(int8_path),'CPU',dict(PERFORMANCE_HINT='LATENCY',NUM_STREAMS=1,INFERENCE_NUM_THREADS=args.threads))
    compile_seconds=time.perf_counter()-started
    assert all('CPU' in name for name in compiled.get_property('EXECUTION_DEVICES'))
    runtime_precision_counts={}
    for node in compiled.get_runtime_model().get_ops():
        info=node.get_rt_info()
        if 'runtimePrecision' in info:
            precision=str(info['runtimePrecision'].value)
            runtime_precision_counts[precision]=runtime_precision_counts.get(precision,0)+1
    runners={
        'fp32_cpu':lambda x:model.model(torch.from_numpy(x))[0].numpy(),
        'onnx_fp16_cpu':lambda x:session.run(None,{session.get_inputs()[0].name:x})[0],
        'openvino_int8_cpu':lambda x:compiled([x])[compiled.output(0)],
    }
    # Same five representative test images for each format; preprocessing outside model-only timing.
    encoded=[p.read_bytes() for p in files[:5]]
    tensors=[preprocess(cv2.imdecode(np.frombuffer(blob,np.uint8),cv2.IMREAD_COLOR)) for blob in encoded]
    rows=[];latency={};end_to_end={}
    with torch.inference_mode():
        for name,runner in runners.items():
            for i in range(args.warmup):runner(tensors[i%len(tensors)])
            runtime_samples=[];pipeline_samples=[]
            for i in range(args.iterations):
                started=time.perf_counter_ns()
                output=runner(tensors[i%len(tensors)])
                elapsed=(time.perf_counter_ns()-started)/1e6
                assert output.shape==(1,16,8400) and np.isfinite(output).all()
                runtime_samples.append(elapsed)
                rows.append(dict(backend=name,kind='model_only',iteration=i,latency_ms=elapsed))
            for i in range(args.iterations):
                started=time.perf_counter_ns()
                frame=cv2.imdecode(np.frombuffer(encoded[i%len(encoded)],np.uint8),cv2.IMREAD_COLOR)
                output=runner(preprocess(frame))
                detections=non_max_suppression(torch.from_numpy(output.copy()),conf_thres=0.25,iou_thres=0.7,nc=12,max_det=300)
                elapsed=(time.perf_counter_ns()-started)/1e6
                assert all(np.isfinite(boxes.numpy()).all() and (boxes[:,5]<12).all() for boxes in detections)
                pipeline_samples.append(elapsed)
                rows.append(dict(backend=name,kind='end_to_end',iteration=i,latency_ms=elapsed))
            latency[name]=latency_summary(runtime_samples,args.warmup,args.threads)
            end_to_end[name]=latency_summary(pipeline_samples,args.warmup,args.threads)
            print(name,latency[name],flush=True)
    with (REPORTS/'latency_samples.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=['backend','kind','iteration','latency_ms'])
        writer.writeheader();writer.writerows(rows)
    delta=accuracy_delta(fp32['map50'],int8['map50'])
    passes=dict(accuracy=delta['strict_0_8pp_pass'],accuracy_test=delta['dod_1_0pp_pass'],
        size=manifest['size_pass'],latency=latency['openvino_int8_cpu']['mean_ms']<20)
    value=dict(source_model='Backend/best.pt',model_version=SOURCE_VERSION,dataset_version=DATA_VERSION,
        environment=environment(),artifacts=manifest,accuracy=dict(fp32=fp32,int8=int8,onnx_fp16=fp16,**delta),
        calibration=json.loads((REPORTS/'calibration_summary.json').read_text()),
        latency=latency,end_to_end_latency=end_to_end,
        runtime_thread_profile=profile,openvino_runtime_node_precision_counts=runtime_precision_counts,
        runtime_settings=dict(onnx_providers=session.get_providers(),onnx_intra_op=args.threads,
            onnx_inter_op=1,openvino_device='CPU',openvino_performance_hint='LATENCY',openvino_streams=1,
            openvino_threads=args.threads,openvino_execution_devices=compiled.get_property('EXECUTION_DEVICES'),
            pytorch_threads=args.threads,pytorch_interop_threads=1,compile_seconds=compile_seconds),
        methodology=dict(model_only='Preprocessed float32 batch1 tensor; synchronous runtime call, outputs materialized; inference_mode',
            end_to_end='In-memory JPEG/PNG decode,letterbox640,RGB normalization,runtime,NMS; excludes disk IO and tracker/alerts',
            images=[p.relative_to(Path(config['path'])).as_posix() for p in files[:5]],
            evaluation_images=len(files),same_test_bytes_sha256=digest(REPORTS/'test_split_manifest.json')),
        speedup_vs_pytorch=latency['fp32_cpu']['mean_ms']/latency['openvino_int8_cpu']['mean_ms'],
        gates=passes,status='PASS' if all(passes.values()) else 'FAIL')
    write_json(args.output,value)
    print('Official CPU quantization benchmark:',value['status'],passes,flush=True)
