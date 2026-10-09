"""Deterministic real QCI-1 train/validation fine-tuning, with untouched test data."""
from __future__ import annotations
import argparse
import csv
import json
import pickle
import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import Any
import numpy as np
import psutil
import torch
from torch import nn
from QCI_1_Surface_Defect_Segmentation.offline import no_network
from QCI_1_Surface_Defect_Segmentation.validation import file_hash
from QCI_1_Surface_Defect_Segmentation.errors import InvalidSampleError
from . import MODEL_VERSION
from .common import ROOT,TASK,REPORTS,CLASSES,deterministic,load_config,write_json
from .contracts import EvaluationResult,ModelArtifact,TrainingConfig
from .data import ManifestDataset,image_label,loader
from .metrics import metrics
from .model import build_model,training_mode,load_checkpoint


def evaluate(model: nn.Module, batches: Any, class_weights: torch.Tensor) -> tuple[EvaluationResult,float]:
    """Evaluate one split with bounded batches and a fixed2x2 confusion matrix."""
    model.eval();matrix=np.zeros((2,2),dtype=np.int64);loss_sum=denominator=0.
    with torch.inference_mode():
        for images,labels,_ in batches:
            logits=model(images)
            if not torch.isfinite(logits).all():raise ValueError('Nonfinite model logits')
            loss_sum+=float(nn.functional.cross_entropy(logits,labels,weight=class_weights,reduction='sum'))
            denominator+=float(class_weights[labels].sum())
            for actual,predicted in zip(labels.tolist(),logits.argmax(1).tolist()):matrix[actual,predicted]+=1
    return metrics(matrix),loss_sum/denominator


@torch.enable_grad()
def train(config: TrainingConfig) -> dict[str,Any]:
    """Train only302 optimization samples; select checkpoints only on validation."""
    deterministic(config.seed,config.threads)
    if config.output_dir.exists():raise ValueError('Existing run preserved; use a fresh versioned output directory')
    data=ManifestDataset(config,'train',True);validation=ManifestDataset(config,'val')
    counts=Counter(image_label(r) for r in data.rows)
    if set(counts)!={0,1}:raise ValueError('Training split must contain both verified classes')
    config.output_dir.mkdir(parents=True)
    train_batches=loader(data,True,config.seed);val_batches=loader(validation,False,config.seed)
    weights=torch.tensor([len(data)/(2*counts[c]) for c in (0,1)],dtype=torch.float32)
    model=build_model(config.starting_weights,config.starting_sha256)
    optimizer=torch.optim.AdamW([dict(params=model.layer4[-1].parameters(),lr=config.learning_rate),
        dict(params=model.fc.parameters(),lr=config.head_learning_rate)],weight_decay=config.weight_decay)
    scheduler=torch.optim.lr_scheduler.CosineAnnealingLR(optimizer,T_max=config.epochs)
    params=sum(p.numel() for p in model.parameters());trained=sum(p.numel() for p in model.parameters() if p.requires_grad)
    source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    lineage=dict(manifest_sha256=file_hash(config.manifest),records_sha256=file_hash(config.records),
        source_commit=source_commit,implementation_sha256={p.name:file_hash(p) for p in TASK.glob('*.py')})
    write_json(config.output_dir/'training_config.json',config.model_dump(mode='json'))
    write_json(config.output_dir/'lineage.json',lineage)
    print('Actual train/val:',len(data),len(validation),'train counts',dict(counts),'weights',weights.tolist(),flush=True)
    print('Parameters:',params,'trainable:',trained,'CPU threads:',config.threads,flush=True)
    best=(-1.,float('inf'));best_epoch=0;bad_epochs=0;started=time.perf_counter();history=[];rss_start=psutil.Process().memory_info().rss/2**20;peak=rss_start
    # Mandatory real mini-batch forward/backward before the full run. No test use.
    images,labels,_=next(iter(train_batches));training_mode(model)
    optimizer.zero_grad(set_to_none=True);smoke_logits=model(images)
    smoke_loss=nn.functional.cross_entropy(smoke_logits,labels,weight=weights)
    if not torch.isfinite(smoke_loss):raise ValueError('Smoke training loss nonfinite')
    smoke_loss.backward();gradient=next(p.grad for p in model.fc.parameters() if p.grad is not None)
    if not torch.isfinite(gradient).all():raise ValueError('Smoke gradient nonfinite')
    optimizer.zero_grad(set_to_none=True)
    write_json(REPORTS/'smoke_training.json',dict(batch_size=len(labels),loss=float(smoke_loss.detach()),output_shape=list(smoke_logits.shape),backward_finite=True,optimizer_step=False))
    del images,labels,smoke_logits,smoke_loss,gradient
    deterministic(config.seed,config.threads);train_batches=loader(data,True,config.seed)
    with (config.output_dir/'history.csv').open('w',encoding='utf-8',newline='') as stream:
        fields=['epoch','train_loss','val_loss','val_accuracy','val_macro_f1','backbone_lr','head_lr','epoch_seconds','rss_mib']
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        for epoch in range(1,config.epochs+1):
            before=time.perf_counter();training_mode(model);train_loss=total_weight=0.
            for images,labels,_ in train_batches:
                optimizer.zero_grad(set_to_none=True);logits=model(images)
                loss=nn.functional.cross_entropy(logits,labels,weight=weights)
                if not torch.isfinite(loss):raise ValueError('Training loss nonfinite')
                loss.backward();nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad],max_norm=5.)
                optimizer.step();denom=float(weights[labels].sum());train_loss+=float(loss.detach())*denom;total_weight+=denom
                peak=max(peak,psutil.Process().memory_info().rss/2**20)
            val,val_loss=evaluate(model,val_batches,weights)
            row=dict(epoch=epoch,train_loss=train_loss/total_weight,val_loss=val_loss,val_accuracy=val.accuracy,
                val_macro_f1=val.macro_f1,backbone_lr=optimizer.param_groups[0]['lr'],head_lr=optimizer.param_groups[1]['lr'],epoch_seconds=time.perf_counter()-before,rss_mib=psutil.Process().memory_info().rss/2**20)
            writer.writerow(row);stream.flush();history.append(row)
            state=dict(architecture='resnet18',model_version=MODEL_VERSION,classes=CLASSES,state_dict=model.state_dict(),epoch=epoch,
                config=config.model_dump(mode='json'),lineage=lineage,validation_metrics=val.model_dump(),validation_loss=val_loss)
            torch.save(state,config.output_dir/'last.pt')
            improved=val.macro_f1>best[0]+1e-12 or (abs(val.macro_f1-best[0])<=1e-12 and val_loss<best[1]-1e-8)
            if improved:
                best=(val.macro_f1,val_loss);best_epoch=epoch;bad_epochs=0;torch.save(state,config.output_dir/'best.pt')
            else:bad_epochs+=1
            scheduler.step()
            print(json.dumps(dict(stage='epoch',**row,best_epoch=best_epoch,patience_used=bad_epochs)),flush=True)
            if bad_epochs>=config.patience:break
    selected,checkpoint=load_checkpoint(config.output_dir/'best.pt')
    reloaded,_=evaluate(selected,val_batches,weights)
    if reloaded.model_dump()!=checkpoint['validation_metrics']:raise ValueError('Selected checkpoint reload does not reproduce validation')
    artifact=ModelArtifact(version=MODEL_VERSION,checkpoint=(config.output_dir/'best.pt').relative_to(ROOT).as_posix(),sha256=file_hash(config.output_dir/'best.pt'),classes=CLASSES,
        parameters=params,trainable_parameters=trained,input_height=config.height,input_width=config.width,starting_weights_sha256=config.starting_sha256,
        manifest_sha256=lineage['manifest_sha256'],records_sha256=lineage['records_sha256'],source_commit=source_commit,best_epoch=best_epoch)
    result=dict(status='training_completed',epochs_requested=config.epochs,epochs_completed=len(history),best_epoch=best_epoch,
        best_validation=reloaded.model_dump(),best_validation_loss=best[1],class_counts=dict(counts),class_weights=weights.tolist(),training_config=config.model_dump(mode='json'),
        dataset_version=data.manifest.version,artifact=artifact.model_dump(),lineage=lineage,duration_seconds=time.perf_counter()-started,
        deterministic_algorithms=True,workers=0,prefetch=None,pin_memory=False,torch_version=torch.__version__,train_memory=dict(start_rss_mib=rss_start,observed_batch_peak_rss_mib=peak,end_rss_mib=psutil.Process().memory_info().rss/2**20),
        held_out_test_evaluated=False,checkpoint_reload_verified=True,numeric_accuracy_target=None,numeric_latency_sla=None)
    write_json(REPORTS/'training_summary.json',result);write_json(REPORTS/'model_artifact.json',artifact.model_dump())
    (REPORTS/'training_history.csv').write_bytes((config.output_dir/'history.csv').read_bytes())
    return result


def main() -> int:
    """Execute entirely offline, recording actual errors and runtime attempts."""
    parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,default=TASK/'configs/qci2_classifier.yaml')
    args=parser.parse_args()
    try:
        with no_network() as audit:result=train(load_config(args.config))
        result.update(offline_verified=True,external_connection_attempts=audit.attempts,runtime_downloads=0)
        write_json(REPORTS/'training_summary.json',result);print(json.dumps(result,indent=2));return 0
    except (OSError,ValueError,RuntimeError,InvalidSampleError,EOFError,pickle.UnpicklingError) as exc:
        print(json.dumps(dict(status='FAILED',error_type=type(exc).__name__,message=str(exc))));return 1


if __name__=='__main__':raise SystemExit(main())
