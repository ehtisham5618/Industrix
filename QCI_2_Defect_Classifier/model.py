"""Local ResNet18 initialization, bounded fine-tuning and safe state reload."""
from __future__ import annotations
from pathlib import Path
from typing import Any
import torch
from torch import nn
from torchvision.models import resnet18
from QCI_1_Surface_Defect_Segmentation.validation import file_hash
from .common import CLASSES


def build_model(starting_weights: Path | None=None, expected_sha256: str | None=None) -> nn.Module:
    """Never pass pretrained enums; load only the verified local state dictionary."""
    model=resnet18(weights=None)
    if starting_weights is not None:
        if not starting_weights.is_file():raise FileNotFoundError('Local initialization weights missing')
        if expected_sha256 is None or file_hash(starting_weights)!=expected_sha256:raise ValueError('Initialization checkpoint checksum mismatch')
        model.load_state_dict(torch.load(starting_weights,map_location='cpu',weights_only=True),strict=True)
    model.fc=nn.Linear(model.fc.in_features,2)
    for parameter in model.parameters():parameter.requires_grad_(False)
    for parameter in model.layer4[-1].parameters():parameter.requires_grad_(True)
    for parameter in model.fc.parameters():parameter.requires_grad_(True)
    return model


def training_mode(model: nn.Module) -> None:
    """Freeze all BatchNorm running statistics for small-data transfer learning."""
    model.train()
    for module in model.modules():
        if isinstance(module,nn.BatchNorm2d):module.eval()


def load_checkpoint(path: Path) -> tuple[nn.Module,dict[str,Any]]:
    """Reject mismatched class/config state; CPU-only weights_only safe loading."""
    if not path.is_file():raise FileNotFoundError('Trained classifier checkpoint missing')
    if path.stat().st_size>64_000_000:raise ValueError('Checkpoint exceeds64MB budget')
    state=torch.load(path,map_location='cpu',weights_only=True)
    if not isinstance(state,dict) or state.get('classes')!=CLASSES or state.get('architecture')!='resnet18' or not isinstance(state.get('model_version'),str):raise ValueError('Checkpoint/class mapping mismatch')
    if not state['model_version'].strip():raise ValueError('Checkpoint model version missing')
    model=build_model();model.load_state_dict(state['state_dict'],strict=True);model.eval()
    return model,state
