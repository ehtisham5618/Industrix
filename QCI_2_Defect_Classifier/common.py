"""Shared deterministic CPU, local config and lightweight JSON utilities."""
from __future__ import annotations
import json
import random
from pathlib import Path
from typing import Any
import numpy as np
import torch
import yaml
from QCI_1_Surface_Defect_Segmentation.config import ROOT, local_path
from .contracts import TrainingConfig

TASK=ROOT/'QCI_2_Defect_Classifier'
REPORTS=ROOT/'reports/qci2'
CLASSES={0:'normal',1:'defect'}


def load_config(path: Path) -> TrainingConfig:
    """Load bounded YAML then resolve every asset to explicit local storage."""
    path=local_path(path)
    if path.stat().st_size>64000:raise ValueError('Configuration exceeds64KB')
    try:raw=yaml.safe_load(path.read_text(encoding='utf-8'))
    except yaml.YAMLError as exc:raise ValueError('Malformed YAML configuration: '+str(exc)) from exc
    cfg=TrainingConfig.model_validate(raw)
    for name in ('manifest','records','output_dir','starting_weights'):setattr(cfg,name,local_path(getattr(cfg,name)))
    if cfg.dataset_root_override is not None:cfg.dataset_root_override=local_path(cfg.dataset_root_override)
    return cfg


def deterministic(seed: int=42, threads: int=2) -> None:
    """Seed Python/NumPy/Torch and require deterministic CPU algorithms."""
    random.seed(seed);np.random.seed(seed);torch.manual_seed(seed)
    torch.set_num_threads(threads);torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.benchmark=False;torch.backends.cudnn.deterministic=True


def write_json(path: Path, value: Any) -> None:
    """Serialize bounded metadata only, rejecting NaN/Infinity."""
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf-8')
