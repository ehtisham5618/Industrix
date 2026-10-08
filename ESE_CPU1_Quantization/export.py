from __future__ import annotations
import ast
import json
from pathlib import Path
import shutil
import time

from .common import (ROOT,REPORTS,RUNTIME,NAMES,SOURCE_VERSION,DATA_VERSION,digest,
    write_json,source_model,dataset_config,environment,calibration,preprocess,evaluate)


def artifact_info(path):
    return dict(path=Path(path).relative_to(ROOT).as_posix(),bytes=Path(path).stat().st_size,sha256=digest(path))


def run(args):
    import cv2
    import numpy as np
    import onnx
    import onnxruntime as ort
    import openvino as ov
    import torch
    import yaml
    from ultralytics import YOLO
    from ultralytics.cfg import DEFAULT_CFG_DICT
    from onnxconverter_common import float16

    REPORTS.mkdir(parents=True,exist_ok=True)
    stage='source verification'
    try:
        assert args.calibration_images==300, 'Official export requires exactly300 calibration images'
        if (args.output_root/'onnx_fp16/best_fp16.onnx').exists() or (args.output_root/'openvino_int8/model.xml').exists():
            raise FileExistsError('Selected deployment already exists; archive it or choose a distinct output-root before export')
        torch.set_num_threads(2)
        model=source_model(args.weights)
        config,data=dataset_config(args.data)
        source_sha=digest(args.weights)
        write_json(REPORTS/'environment.json',environment())
        write_json(REPORTS/'source_lineage.json',dict(model_version=SOURCE_VERSION,
            dataset_version=DATA_VERSION,checkpoint_sha256=source_sha,names=NAMES,
            parameters=sum(p.numel() for p in model.model.parameters()),
            architecture='YOLOv8s',source_bytes=args.weights.stat().st_size,
            dataset_yaml=args.data.relative_to(ROOT).as_posix(),train=str(config['train']),
            val=str(config['val']),test=str(config['test']),
            no_retraining=True,source_model_known_shortfall='CME-OPT2 chemical/smoke targets not met'))
        stage='FP32 held-out baseline'
        if not args.skip_baseline:
            result=evaluate(args.weights,data,'fp32')
            result.update(checkpoint_sha256=source_sha)
            write_json(REPORTS/'fp32_metrics.json',result)
        else:
            assert json.loads((REPORTS/'fp32_metrics.json').read_text())['checkpoint_sha256']==source_sha
        stage='calibration selection'
        selected,manifest=calibration(config,args.calibration_images,args.seed)
        # The exporter takes a fraction, not an image count. The file contains
        # exactly300 training paths and split=train/fraction=1 selects all of them.
        calib=dict(config,train=str(manifest),val=str(manifest))
        calib_path=RUNTIME/'calibration.yaml'
        calib_path.write_text(yaml.safe_dump(calib),encoding='utf-8')
        stage='ONNX FP32 intermediate'
        copy=RUNTIME/'source.pt'
        shutil.copy2(args.weights,copy)
        exporter=YOLO(str(copy))
        onnx_path=Path(exporter.export(format='onnx',imgsz=640,batch=1,device='cpu',
            half=False,opset=17,simplify=False,dynamic=False,nms=False))
        stage='ONNX FP16 conversion and CPU validation'
        graph=onnx.load(str(onnx_path))
        graph=float16.convert_float_to_float16(graph,keep_io_types=True,disable_shape_infer=False)
        onnx.checker.check_model(graph)
        fp16_dir=args.output_root/'onnx_fp16'
        fp16_dir.mkdir(parents=True,exist_ok=True)
        fp16_path=fp16_dir/'best_fp16.onnx'
        onnx.save(graph,str(fp16_path))
        session_options=ort.SessionOptions();session_options.intra_op_num_threads=2;session_options.inter_op_num_threads=1
        session=ort.InferenceSession(str(fp16_path),session_options,providers=['CPUExecutionProvider'])
        assert session.get_providers()==['CPUExecutionProvider']
        assert sum(t.data_type==onnx.TensorProto.FLOAT16 for t in graph.graph.initializer)>0
        smoke=[]
        model.model.float().eval().to('cpu')
        with torch.inference_mode():
            for image in selected[:5]:
                tensor=preprocess(cv2.imread(str(image)))
                expected=model.model(torch.from_numpy(tensor))[0].numpy()
                output=session.run(None,{session.get_inputs()[0].name:tensor})[0]
                assert output.shape==expected.shape==(1,16,8400) and np.isfinite(output).all()
                smoke.append(dict(image=image.relative_to(Path(config['path'])).as_posix(),
                    output_shape=list(output.shape),onnx_fp16_max_absolute_delta=float(np.abs(output-expected).max()),
                    onnx_fp16_mean_absolute_delta=float(np.abs(output-expected).mean())))
        stage='OpenVINO NNCF INT8 PTQ'
        # Version8.4.24 uses int8/half, not newer quantize. Avoid passing unsupported arguments.
        assert 'int8' in DEFAULT_CFG_DICT and 'quantize' not in DEFAULT_CFG_DICT
        int8_path=Path(YOLO(str(copy)).export(format='openvino',int8=True,half=False,
            data=str(calib_path),split='train',fraction=1.0,imgsz=640,batch=1,device='cpu',dynamic=False,nms=False))
        target=args.output_root/'openvino_int8'
        target.mkdir(parents=True,exist_ok=True)
        if (target/'model.xml').exists():
            raise FileExistsError('Refusing to overwrite selected deployment artifacts; move previous version first')
        source_xml=next(int8_path.glob('*.xml'))
        shutil.copy2(source_xml,target/'model.xml')
        shutil.copy2(source_xml.with_suffix('.bin'),target/'model.bin')
        shutil.copy2(int8_path/'metadata.yaml',target/'metadata.yaml')
        stage='OpenVINO CPU validation'
        core=ov.Core(); network=core.read_model(target/'model.xml')
        compiled=core.compile_model(network,'CPU',{'PERFORMANCE_HINT':'LATENCY','NUM_STREAMS':1,'INFERENCE_NUM_THREADS':2})
        assert all('CPU' in d for d in compiled.get_property('EXECUTION_DEVICES'))
        quantization_ops=sum(op.get_type_name()=='FakeQuantize' for op in network.get_ops())
        constant_bytes={}
        for op in network.get_ops():
            if op.get_type_name()=='Constant':
                kind=str(op.get_element_type())
                constant_bytes[kind]=constant_bytes.get(kind,0)+op.data.nbytes
        assert quantization_ops>0, 'Artifact is not an NNCF activation-quantized graph'
        for item,image in zip(smoke,selected[:5]):
            output=compiled([preprocess(cv2.imread(str(image)))])[compiled.output(0)]
            assert output.shape==(1,16,8400) and np.isfinite(output).all()
            item['openvino_shape']=list(output.shape);item['openvino_finite']=True
        write_json(REPORTS/'smoke_validation.json',dict(images=smoke,onnx_provider=session.get_providers(),
            onnx_checker_pass=True,openvino_execution_devices=compiled.get_property('EXECUTION_DEVICES')))
        artifacts={name:artifact_info(path) for name,path in dict(onnx_fp16=fp16_path,
            openvino_xml=target/'model.xml',openvino_bin=target/'model.bin',metadata=target/'metadata.yaml').items()}
        core_bytes=artifacts['openvino_xml']['bytes']+artifacts['openvino_bin']['bytes']
        write_json(REPORTS/'artifact_manifest.json',dict(source_model_version=SOURCE_VERSION,
            source_sha256=source_sha,dataset_version=DATA_VERSION,artifacts=artifacts,
            combined_core_bytes=core_bytes,combined_core_decimal_mb=core_bytes/1e6,
            combined_core_mib=core_bytes/2**20,required_metadata_bytes=artifacts['metadata']['bytes'],
            complete_runtime_bytes=core_bytes+artifacts['metadata']['bytes'],
            size_target_bytes=6500000,size_pass=core_bytes<6500000,
            nncf_fake_quantize_ops=quantization_ops,constant_bytes_by_precision=constant_bytes,
            export_api='Ultralytics8.4.24 int8=True; fraction1.0 over exactly300 training paths',
            detection_head_policy='Unmodified upstream ignored Add/Sub/Mul/Div detection-head patterns and Sigmoid; MIXED preset',
            onnx_fp16_policy='CPU FP32 ONNX export, onnxconverter-common FP16 conversion with FP32 IO; CPU EP may promote unsupported kernels',
            versions=environment()['packages']))
        assert digest(args.weights)==source_sha
        print('Validated FP16 and genuine NNCF INT8 artifacts generated; combined IR bytes=',core_bytes,flush=True)
    except Exception as exc:
        write_json(REPORTS/'export_failure.json',dict(stage=stage,error=repr(exc),environment=environment()))
        raise
