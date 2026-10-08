"""Select PTQ using validation only, with NNCF accuracy control if needed."""
from __future__ import annotations
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

from .common import (ROOT,REPORTS,RUNTIME,NAMES,preprocess,dataset_config,evaluate,
    accuracy_delta,write_json,digest)
from .export import artifact_info


def validation_callback(data):
    """NNCF validation uses the original Ultralytics metric/NMS implementation."""
    import torch
    from ultralytics.models.yolo.detect import DetectionValidator
    from ultralytics.data.utils import check_det_dataset
    args=dict(data=str(data),split='val',imgsz=640,batch=1,workers=0,rect=False,
        conf=0.001,iou=0.7,max_det=300,half=False,plots=False,save_json=False,
        project=str(RUNTIME/'accuracy_control'),name='validation',exist_ok=True,device='cpu')

    def fresh():
        validator=DetectionValidator(args=args)
        validator.device=torch.device('cpu');validator.data=check_det_dataset(str(data))
        validator.stride=32;validator.training=False
        validator.init_metrics(SimpleNamespace(names=dict(enumerate(NAMES)),end2end=False))
        return validator

    builder=fresh()
    loader=builder.get_dataloader(builder.data['val'],1)

    def callback(model,validation_data):
        validator=fresh()
        iterable=validation_data.get_data() if hasattr(validation_data,'get_data') else validation_data
        with torch.inference_mode():
            for batch in iterable:
                # Preprocess copies device tensors; do not normalize a cached batch in place.
                batch=validator.preprocess(dict(batch))
                predictions=model([batch['img'].numpy()])[model.output(0)]
                validator.update_metrics(validator.postprocess(torch.from_numpy(predictions)),batch)
        validator.get_stats()
        return float(validator.metrics.box.map50)
    return loader,callback


def main():
    import argparse
    import cv2
    import nncf
    import openvino as ov
    import yaml
    from ultralytics import YOLO

    parser=argparse.ArgumentParser()
    parser.add_argument('--resume-baseline',action='store_true',help='Reuse same verified source baseline after a format-wrapper recovery')
    parser.add_argument('--force-accuracy-aware',action='store_true',help='Investigate a strict held-out shortfall using validation-only accuracy control')
    args=parser.parse_args()
    _,data=dataset_config(ROOT/'Hazard_Expansion/configs/12class_data.yaml')
    if args.resume_baseline:
        fp32=json.loads((REPORTS/'fp32_validation_metrics.json').read_text())
        lineage=json.loads((REPORTS/'source_lineage.json').read_text())
        assert lineage['checkpoint_sha256']==digest(ROOT/'Backend/best.pt')
        assert fp32['split']=='val' and fp32['rect'] is False and fp32['imgsz']==640
    else:
        fp32=evaluate(ROOT/'Backend/best.pt',data,'fp32_validation',split='val')
    target=ROOT/'Backend/weights/openvino_int8'
    cached=REPORTS/'basic_int8_validation_metrics.json'
    if args.force_accuracy_aware and args.resume_baseline and cached.exists():
        basic=json.loads(cached.read_text())
        assert basic['artifact_sha256']==digest(target/'model.xml')
        assert basic['artifact_bin_sha256']==digest(target/'model.bin')
    else:
        basic=evaluate(target/'model.xml',data,'basic_int8_validation',split='val')
    delta=accuracy_delta(fp32['map50'],basic['map50'])
    attempts=[dict(attempt=1,type='standard_nncf_ptq',selection_split='val',**delta)]
    if not delta['strict_0_8pp_pass'] or args.force_accuracy_aware:
        print('Investigating strict accuracy target with NNCF accuracy-aware PTQ on validation only.',flush=True)
        backup=RUNTIME/'basic_ptq'
        shutil.copytree(target,backup,dirs_exist_ok=True)
        original=Path(YOLO(str(RUNTIME/'source.pt')).export(format='openvino',half=False,int8=False,
            imgsz=640,batch=1,device='cpu',dynamic=False,nms=False))
        graph=ov.Core().read_model(next(original.glob('*.xml')))
        from ultralytics.data import build_dataloader
        from ultralytics.data.dataset import YOLODataset
        from ultralytics.data.utils import check_det_dataset
        calibration_cfg=check_det_dataset(str(RUNTIME/'calibration.yaml'))
        calibration_set=YOLODataset(calibration_cfg['train'],data=calibration_cfg,task='detect',
            imgsz=640,augment=False,batch_size=1,fraction=1.0)
        assert len(calibration_set)==300
        calibration_loader=build_dataloader(calibration_set,batch=1,workers=0,shuffle=False)
        calibration_data=nncf.Dataset(calibration_loader,lambda batch:batch['img'].numpy().astype('float32')/255)
        loader,callback=validation_callback(data)
        validation_data=nncf.Dataset(loader,lambda batch:batch['img'].numpy().astype('float32')/255)
        ignored=nncf.IgnoredScope(patterns=[r'.*model.22/.*/Add',r'.*model.22/.*/Sub*',
            r'.*model.22/.*/Mul*',r'.*model.22/.*/Div*'],types=['Sigmoid'])
        try:
            quantized=nncf.quantize_with_accuracy_control(graph,calibration_data,validation_data,callback,
                max_drop=0.0079,drop_type=nncf.DropType.ABSOLUTE,subset_size=300,
                preset=nncf.QuantizationPreset.MIXED,ignored_scope=ignored,target_device=nncf.TargetDevice.CPU)
            ov.save_model(quantized,target/'model.xml',compress_to_fp16=False)
            result=evaluate(target/'model.xml',data,'accuracy_aware_validation',split='val')
            adjusted=accuracy_delta(fp32['map50'],result['map50'])
            attempts.append(dict(attempt=2,type='nncf_accuracy_control',selection_split='val',
                trigger='strict held-out target shortfall' if args.force_accuracy_aware else 'validation target shortfall',
                max_drop=0.0079,**adjusted))
            if not adjusted['strict_0_8pp_pass']:
                raise RuntimeError('Accuracy-aware PTQ did not meet the strict validation target')
            manifest=json.loads((REPORTS/'artifact_manifest.json').read_text())
            manifest['artifacts']['openvino_xml']=artifact_info(target/'model.xml')
            manifest['artifacts']['openvino_bin']=artifact_info(target/'model.bin')
            total=sum(manifest['artifacts'][key]['bytes'] for key in ('openvino_xml','openvino_bin'))
            manifest.update(combined_core_bytes=total,combined_core_decimal_mb=total/1e6,
                combined_core_mib=total/2**20,complete_runtime_bytes=total+manifest['required_metadata_bytes'],
                size_pass=total<6500000,selected_ptq='accuracy_aware')
            manifest['export_api']='Ultralytics8.4.24 FP32 OpenVINO conversion; NNCF quantize_with_accuracy_control; absolute max_drop0.0079;targetCPU;MIXED;exactly300 training samples'
            manifest['nncf_fake_quantize_ops']=sum(op.get_type_name()=='FakeQuantize' for op in quantized.get_ops())
            manifest['constant_bytes_by_precision']={}
            for op in quantized.get_ops():
                if op.get_type_name()=='Constant':
                    kind=str(op.get_element_type());old=manifest['constant_bytes_by_precision'].get(kind,0)
                    manifest['constant_bytes_by_precision'][kind]=old+op.data.nbytes
            write_json(REPORTS/'artifact_manifest.json',manifest)
        except Exception as exc:
            attempts.append(dict(attempt=2,type='nncf_accuracy_control',error=repr(exc),selection_split='val'))
            shutil.copytree(backup,target,dirs_exist_ok=True)
            write_json(REPORTS/'ptq_selection.json',dict(attempts=attempts,selected='basic_target_shortfall',test_not_used_for_selection=True))
            raise
    write_json(REPORTS/'ptq_selection.json',dict(attempts=attempts,
        selected='basic' if len(attempts)==1 else 'accuracy_aware',test_not_used_for_selection=True))
    print('PTQ selection complete without test feedback.',flush=True)


if __name__=='__main__':main()
