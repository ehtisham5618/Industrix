"""Resolve repository-relative local paths and reuse the dataset's actual YAML."""
from __future__ import annotations

import ctypes
import sys
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .contracts import ClassMapping, DatasetConfig
from .errors import ConfigurationError

ROOT = Path(__file__).resolve().parents[1]


def local_path(value: str | Path, base: Path = ROOT) -> Path:
    """Reject remote/UNC/mapped storage before and after resolving symlinks."""
    text=str(value)
    if not text.strip() or text.startswith(('\\\\','//')) or '://' in text or (':' in text and not (len(text)>2 and text[0].isalpha() and text[1]==':' and text[2] in '/\\')):
        raise ConfigurationError('Expected a nonempty local filesystem path')
    path=Path(value)
    path=(base/path if not path.is_absolute() else path).resolve()
    if str(path).startswith(('\\\\','//')):
        raise ConfigurationError('Resolved path uses network storage')
    if sys.platform=='win32':
        get_type=ctypes.windll.kernel32.GetDriveTypeW
        get_type.argtypes=[ctypes.c_wchar_p];get_type.restype=ctypes.c_uint
        if get_type(path.anchor) not in (2,3,6):
            raise ConfigurationError('Mapped/network/unknown drives are not local inputs')
    return path


def inside(path: Path, root: Path) -> Path:
    """Reject linked or configured files outside their explicit dataset root."""
    resolved=local_path(path)
    if not resolved.is_relative_to(root.resolve()):
        raise ConfigurationError('Input path escapes dataset root')
    return resolved


def load_config(path: Path) -> DatasetConfig:
    """Read a bounded YAML config; relative deployment paths use repo root."""
    try:
        path=local_path(path)
        if path.stat().st_size>64_000:raise ConfigurationError('Config exceeds 64 KB')
        raw=yaml.safe_load(path.read_text(encoding='utf-8'))
        if not isinstance(raw,dict):raise ConfigurationError('Config must be a mapping')
        config=DatasetConfig.model_validate(raw)
        config.dataset_root=local_path(config.dataset_root)
        config.output_dir=local_path(config.output_dir)
        if config.output_dir==config.dataset_root or config.output_dir.is_relative_to(config.dataset_root):
            raise ConfigurationError('Outputs must not be written inside the source dataset')
        return config
    except (OSError,ValueError,ValidationError,yaml.YAMLError) as exc:
        raise ConfigurationError(str(exc)) from exc


def read_mapping(config: DatasetConfig) -> tuple[ClassMapping, dict[str, Any]]:
    """Use names/nc from actual source data.yaml; never fill unknown classes."""
    path=inside(config.dataset_root/config.metadata_file,config.dataset_root)
    try:
        if path.stat().st_size>64_000:raise ConfigurationError('Dataset metadata exceeds 64 KB')
        raw=yaml.safe_load(path.read_text(encoding='utf-8'))
        if not isinstance(raw,dict):raise ConfigurationError('Dataset metadata must be a mapping')
        names=raw.get('names')
        if isinstance(names,list):names={i:n for i,n in enumerate(names)}
        elif isinstance(names,dict):names={int(k):v for k,v in names.items()}
        else:raise ConfigurationError('Source metadata has no canonical names')
        mapping=ClassMapping(source=config.metadata_file,names=names)
        if raw.get('nc',len(names))!=len(names):raise ConfigurationError('nc differs from class mapping')
        return mapping,raw
    except (OSError,ValueError,TypeError,yaml.YAMLError) as exc:
        raise ConfigurationError(str(exc)) from exc
