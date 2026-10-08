"""CPU-only adapter for the selected, static batch-one CPU1 OpenVINO artifact."""
from __future__ import annotations

import csv
import json
import threading
import time
from collections import deque
from pathlib import Path

from ESE_CPU1_Quantization.common import ROOT, NAMES, digest, preprocess


class OpenVINODetector:
    def __init__(self, model_dir=None, timing_path=None, threads=2, hint='LATENCY', streams=1):
        import openvino as ov
        import yaml
        self.model_dir=Path(model_dir or ROOT/'Backend/weights/openvino_int8')
        manifest=json.loads((ROOT/'ESE_CPU1_Quantization/reports/artifact_manifest.json').read_text())
        for key in ('openvino_xml','openvino_bin','metadata'):
            item=manifest['artifacts'][key]
            path=self.model_dir/Path(item['path']).name
            if not path.is_file() or digest(path)!=item['sha256']:
                raise RuntimeError('Selected CPU1 artifact is missing or its hash changed: '+path.name)
        metadata=yaml.safe_load((self.model_dir/'metadata.yaml').read_text())
        self.names=metadata['names']
        if [self.names[i] for i in range(12)]!=NAMES:
            raise ValueError('Selected OpenVINO class mapping differs from the trained model')
        started=time.perf_counter()
        self.compiled=ov.Core().compile_model(str(self.model_dir/'model.xml'),'CPU',
            dict(PERFORMANCE_HINT=hint,NUM_STREAMS=streams,INFERENCE_NUM_THREADS=threads))
        devices=self.compiled.get_property('EXECUTION_DEVICES')
        if devices!=['CPU'] or list(self.compiled.input(0).shape)!=[1,3,640,640]:
            raise RuntimeError('Required engine is static batch-one 640x640 on CPU')
        precisions={}
        for node in self.compiled.get_runtime_model().get_ops():
            info=node.get_rt_info()
            if 'runtimePrecision' in info:
                precision=str(info['runtimePrecision'].value)
                precisions[precision]=precisions.get(precision,0)+1
        if not any(k.lower() in ('i8','u8') for k in precisions):
            raise RuntimeError('Compiled CPU engine contains no verified INT8 operations')
        self.request=self.compiled.create_infer_request()
        self.output=self.compiled.output(0)
        self.input=self.compiled.input(0)
        self.verification=dict(device='CPU',execution_devices=devices,input_shape=[1,3,640,640],
            output_shape=list(self.output.shape),class_names=self.names,artifact_manifest=manifest,
            runtime_precision_counts=precisions,openvino_version=ov.__version__,
            settings=dict(performance_hint=str(self.compiled.get_property('PERFORMANCE_HINT')),
                          num_streams=int(self.compiled.get_property('NUM_STREAMS')),
                          threads=int(self.compiled.get_property('INFERENCE_NUM_THREADS'))),
            compilation_seconds=time.perf_counter()-started)
        self.started_at=time.perf_counter()
        self.warmup_seconds=0
        self.calls=0
        self.errors=[]
        self.recent=deque(maxlen=128)
        self.lock=threading.Lock()
        self.log=Path(timing_path).open('w',newline='',encoding='utf-8') if timing_path else None
        self.writer=csv.DictWriter(self.log,fieldnames=['elapsed_seconds','inference_ms','preprocess_ms','nms_ms']) if self.log else None
        if self.writer:self.writer.writeheader()

    def infer_tensor(self,tensor):
        import numpy as np
        started=time.perf_counter_ns()
        output=self.request.infer({self.input:tensor},share_outputs=False)[self.output]
        elapsed=(time.perf_counter_ns()-started)/1e6
        if output.shape!=(1,16,8400) or not np.isfinite(output).all():
            raise RuntimeError('OpenVINO produced invalid/nonfinite YOLO output')
        return output,elapsed

    def predict_batch(self,frames):
        import torch
        from ultralytics.utils.nms import non_max_suppression
        from ultralytics.utils.ops import scale_boxes
        started=time.perf_counter()
        outputs=[]
        try:
            for frame in frames:
                before=time.perf_counter_ns()
                tensor=preprocess(frame)
                preprocess_ms=(time.perf_counter_ns()-before)/1e6
                raw,inference_ms=self.infer_tensor(tensor)
                before=time.perf_counter_ns()
                boxes=non_max_suppression(torch.from_numpy(raw),conf_thres=.25,iou_thres=.7,nc=12,max_det=300)[0]
                if len(boxes):scale_boxes((640,640),boxes[:,:4],frame.shape[:2])
                detections=[]
                for x1,y1,x2,y2,confidence,class_id in boxes.tolist():
                    class_id=int(class_id)
                    if not 0<=class_id<12:raise RuntimeError('Detector class ID outside model mapping')
                    detections.append(dict(class_id=class_id,class_name=self.names[class_id],confidence=confidence,
                        coordinates=dict(x1=x1,y1=y1,x2=x2,y2=y2)))
                nms_ms=(time.perf_counter_ns()-before)/1e6
                elapsed=time.perf_counter()-self.started_at
                with self.lock:
                    self.calls+=1
                    self.recent.append((inference_ms,preprocess_ms,nms_ms))
                if self.writer:
                    self.writer.writerow(dict(elapsed_seconds=elapsed,inference_ms=inference_ms,
                                              preprocess_ms=preprocess_ms,nms_ms=nms_ms))
                outputs.append(detections)
        except Exception as exc:
            import traceback
            self.errors.append(dict(component='OpenVINO/preprocessing/NMS',elapsed_seconds=time.perf_counter()-self.started_at,
                timestamp=time.time(),exception_class=type(exc).__name__,message=str(exc),traceback=traceback.format_exc()))
            raise
        return outputs,time.perf_counter()-started

    def snapshot(self):
        with self.lock:
            return self.calls,list(self.recent)

    def close(self):
        if self.log:self.log.flush();self.log.close();self.log=None
