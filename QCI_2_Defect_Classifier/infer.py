"""Reusable local predictions and genuine scoped Grad-CAM, with typed failures."""
from __future__ import annotations
import argparse
import hashlib
import json
import logging
import pickle
import threading
import time
from pathlib import Path
from typing import Any
import cv2
import numpy as np
import torch
from torch import nn
from PIL import Image
from QCI_1_Surface_Defect_Segmentation.config import local_path
from QCI_1_Surface_Defect_Segmentation.contracts import DatasetConfig
from QCI_1_Surface_Defect_Segmentation.preprocessing import prepare
from QCI_1_Surface_Defect_Segmentation.validation import decode_image,file_hash
from QCI_1_Surface_Defect_Segmentation.offline import no_network
from QCI_1_Surface_Defect_Segmentation.errors import InvalidSampleError
from .common import ROOT,CLASSES,REPORTS,deterministic,write_json
from .contracts import PredictionRequest,PredictionResult,ClassScore,HeatmapResult,TrainingConfig
from .model import load_checkpoint

LOGGER=logging.getLogger('qci2')
CONTROLLED=(OSError,ValueError,RuntimeError,EOFError,KeyError,TypeError,pickle.UnpicklingError,InvalidSampleError,cv2.error)


def normalize_cam(cam: np.ndarray) -> tuple[np.ndarray,bool]:
    """Finite nonnegative0..1 attribution; degenerate maps explicitly stay zero."""
    if cam.ndim!=2 or not np.isfinite(cam).all():raise ValueError('Grad-CAM is not finite2D')
    cam=np.maximum(cam,0).astype(np.float32)
    span=float(cam.max()-cam.min())
    if span<=1e-12:return np.zeros_like(cam),True
    return (cam-cam.min())/span,False


def grad_cam(model: nn.Module, tensor: torch.Tensor, target: int, layer: nn.Module) -> tuple[np.ndarray,bool]:
    """Gradients of the actual target logit weight final-convolution activations."""
    if type(target) is not int or target not in (0,1):raise ValueError('Invalid binary attribution target')
    captured:list[torch.Tensor]=[]
    def capture(module: nn.Module, inputs: tuple[torch.Tensor,...], output: torch.Tensor) -> None:
        captured.append(output)
    handle=layer.register_forward_hook(capture)
    try:
        with torch.inference_mode(False),torch.enable_grad():
            # Never preserve an inference-mode tensor in the attribution graph.
            value=tensor.detach().clone().requires_grad_(True)
            logits=model(value)
            if len(captured)!=1 or logits.shape!=(1,2) or not torch.isfinite(logits).all():raise ValueError('Invalid attribution forward pass')
            activations=captured[0]
            gradients=torch.autograd.grad(logits[0,target],activations,retain_graph=False,create_graph=False)[0]
            weights=gradients.mean(dim=(2,3),keepdim=True)
            raw=torch.relu((weights*activations).sum(dim=1))[0].detach().cpu().numpy().copy()
        return normalize_cam(raw)
    finally:
        handle.remove();captured.clear();model.zero_grad(set_to_none=True)


class DefectClassifier:
    """One local loaded model, serialized requests and no retained heatmap tensors."""
    def __init__(self, checkpoint: Path, expected_sha256: str | None=None, telemetry=None) -> None:
        self.lock=threading.RLock();self.error:Exception | None=None;self.model:nn.Module | None=None
        self.metadata:dict[str,Any]={};self.config:TrainingConfig | None=None
        try:
            checkpoint=local_path(checkpoint)
            if expected_sha256 is not None and file_hash(checkpoint)!=expected_sha256:raise ValueError('Trained model checksum mismatch')
            self.model,self.metadata=load_checkpoint(checkpoint)
            self.config=TrainingConfig.model_validate(self.metadata['config'])
            self.target_name='layer4.1.conv2'
            self.target_layer=self.model.get_submodule(self.target_name)
            if not isinstance(self.target_layer,nn.Conv2d) or self.target_layer.out_channels!=512:raise ValueError('Grad-CAM target is not the inspected final ResNet18 convolution')
            # State is already copied into the model; metadata must not retain
            # a second full tensor dictionary for every loaded service instance.
            self.metadata.pop('state_dict',None)
        except CONTROLLED as exc:self.error=exc;self.model=None
        from QCI_4_Edge_Telemetry.inference import get_tracker
        self.telemetry=telemetry if telemetry is not None else get_tracker()
        try:self.telemetry.bind(self)
        except Exception as exc:LOGGER.warning('QCI4_OBSERVER_ERROR error_type=%s',type(exc).__name__)

    def _observe(self,result):
        """Best-effort bounded local metrics; monitoring failure never changes prediction."""
        try:self.telemetry.observe(result)
        except Exception as exc:LOGGER.warning('QCI4_OBSERVER_ERROR error_type=%s',type(exc).__name__)

    def predict(self, request: PredictionRequest | dict[str,Any]) -> PredictionResult:
        """Return controlled failure for invalid inputs; persist only requested maps."""
        sample_id='invalid_request'
        try:
            request=PredictionRequest.model_validate(request);sample_id=request.image.name
            if self.error is not None:raise self.error
            if self.model is None or self.config is None:raise RuntimeError('Classifier not loaded')
            if request.target_class is not None and not request.heatmap:raise ValueError('Target class requires heatmap generation')
            with self.lock:
                started=time.perf_counter();path=local_path(request.image)
                if path.suffix.lower() not in ('.png','.jpg','.jpeg','.bmp','.tif','.tiff','.webp'):raise ValueError('Unsupported image file type')
                decode_config=DatasetConfig(dataset_root=path.parent,output_dir=REPORTS,target_height=self.config.height,target_width=self.config.width,max_pixels=2_000_000)
                image,_=decode_image(path,decode_config);prepared=prepare(image,None,decode_config)
                tensor=torch.from_numpy(prepared.tensor())
                tensor=((tensor-torch.tensor([.485,.456,.406])[:,None,None])/torch.tensor([.229,.224,.225])[:,None,None]).unsqueeze(0)
                before=time.perf_counter()
                with torch.inference_mode():scores=torch.softmax(self.model(tensor)[0],dim=0).cpu().numpy().copy()
                classification_ms=(time.perf_counter()-before)*1000
                if scores.shape!=(2,) or not np.isfinite(scores).all():raise ValueError('Invalid classifier output')
                predicted=int(np.argmax(scores));warnings=[];explanation=None;cam_ms=0.
                if float(scores[predicted])<self.config.low_confidence_threshold:warnings.append('LOW_CONFIDENCE_UNCALIBRATED_SOFTMAX')
                if request.heatmap:
                    before=time.perf_counter();target=predicted if request.target_class is None else request.target_class
                    raw,degenerate=grad_cam(self.model,tensor,target,self.target_layer)
                    # Undo the exact letterbox geometry; explanation aligns to source pixels.
                    transform=prepared.transform
                    expanded=cv2.resize(raw,(self.config.width,self.config.height),interpolation=cv2.INTER_LINEAR)
                    expanded=expanded[transform.pad_top:transform.pad_top+transform.resized_height,transform.pad_left:transform.pad_left+transform.resized_width]
                    aligned=cv2.resize(expanded,(image.shape[1],image.shape[0]),interpolation=cv2.INTER_LINEAR)
                    aligned,aligned_degenerate=normalize_cam(aligned);degenerate=degenerate or aligned_degenerate
                    raw_path=overlay_path=None
                    if request.output_dir is not None:
                        destination=local_path(request.output_dir)
                        if destination==path.parent or destination.is_relative_to(path.parent):raise ValueError('Heatmaps must not be written into the source image directory')
                        destination.mkdir(parents=True,exist_ok=True)
                        identity=file_hash(path)[:16]+f'_class{target}'
                        raw_file=destination/(identity+'_heatmap.png');overlay_file=destination/(identity+'_overlay.png')
                        color=cv2.cvtColor(cv2.applyColorMap(np.rint(aligned*255).astype(np.uint8),cv2.COLORMAP_TURBO),cv2.COLOR_BGR2RGB)
                        strength=(.35*aligned[:,:,None]).astype(np.float32)
                        overlay=np.rint(image*(1-strength)+color*strength).clip(0,255).astype(np.uint8)
                        Image.fromarray(np.rint(aligned*255).astype(np.uint8)).save(raw_file)
                        Image.fromarray(overlay).save(overlay_file)
                        raw_path=str(raw_file);overlay_path=str(overlay_file)
                    explanation=HeatmapResult(target_layer=self.target_name,target_class_id=target,target_class_name=CLASSES[target],width=image.shape[1],height=image.shape[0],
                        minimum=float(aligned.min()),maximum=float(aligned.max()),degenerate=degenerate,raw_heatmap_path=raw_path,overlay_path=overlay_path)
                    if degenerate:warnings.append('DEGENERATE_GRAD_CAM_NO_POSITIVE_ATTRIBUTION')
                    cam_ms=(time.perf_counter()-before)*1000
                result=PredictionResult(status='SUCCESS',sample_id=sample_id,model_version=self.metadata['model_version'],predicted_class_id=predicted,predicted_class_name=CLASSES[predicted],confidence=float(scores[predicted]),
                    class_scores=[ClassScore(class_id=i,class_name=CLASSES[i],score=float(scores[i])) for i in (0,1)],classifier_latency_ms=classification_ms,heatmap_latency_ms=cam_ms,combined_latency_ms=(time.perf_counter()-started)*1000,heatmap=explanation,warnings=warnings)
                LOGGER.info(json.dumps(dict(stage='prediction',sample_id=sample_id,model_version=result.model_version,prediction=predicted,confidence=result.confidence,latency_ms=result.combined_latency_ms,heatmap_status='degenerate' if explanation and explanation.degenerate else 'generated' if explanation else 'not_requested')))
                self._observe(result)
                return result
        except CONTROLLED as exc:
            LOGGER.warning(json.dumps(dict(stage='prediction',sample_id=sample_id,error_type=type(exc).__name__,message=str(exc)[:500])))
            result=PredictionResult(status='FAILED',sample_id=sample_id,error_type=type(exc).__name__,error_message=str(exc)[:500])
            self._observe(result)
            return result


def main() -> int:
    """Offline inference CLI; missing/bad models do not trigger downloads."""
    parser=argparse.ArgumentParser();parser.add_argument('--image',type=Path,required=True)
    parser.add_argument('--model',type=Path,default=ROOT/'QCI_2_Defect_Classifier/runtime/run_v1/best.pt')
    parser.add_argument('--output',type=Path,default=REPORTS/'heatmaps')
    parser.add_argument('--json',type=Path);parser.add_argument('--target-class',type=int);parser.add_argument('--no-heatmap',action='store_true')
    args=parser.parse_args();deterministic();logging.basicConfig(level=logging.INFO,format='%(message)s')
    with no_network() as audit:
        classifier=DefectClassifier(args.model)
        result=classifier.predict(dict(image=str(args.image),heatmap=not args.no_heatmap,target_class=args.target_class,output_dir=str(args.output)))
        if audit.attempts:raise RuntimeError('Unexpected offline network attempt')
    if args.json:write_json(local_path(args.json),result.model_dump(mode='json'))
    print(result.model_dump_json(indent=2));return 0 if result.status=='SUCCESS' else 1


if __name__=='__main__':raise SystemExit(main())
