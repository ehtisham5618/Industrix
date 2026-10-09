"""Deterministic RGB letterboxing; categorical masks only use nearest neighbor."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray
from PIL import Image

from .contracts import DatasetConfig, Transform
from .validation import IndexedMask, RGBImage


@dataclass
class PreparedSample:
    """One sample's buffers; normalized tensors are computed lazily, never cached."""
    image: RGBImage
    mask: IndexedMask | None
    transform: Transform

    def tensor(self) -> NDArray[np.float32]:
        """Return the explicitly documented RGB float32 CHW [0,1] contract."""
        return np.ascontiguousarray(self.image.transpose(2,0,1),dtype=np.float32)/np.float32(255)


def prepare(image: RGBImage, mask: IndexedMask | None, config: DatasetConfig) -> PreparedSample:
    """Apply identical aspect-preserving geometry and distinct interpolation."""
    height,width=image.shape[:2];scale=min(config.target_width/width,config.target_height/height)
    rw=max(1,min(config.target_width,round(width*scale)));rh=max(1,min(config.target_height,round(height*scale)))
    left=(config.target_width-rw)//2;top=(config.target_height-rh)//2
    output=np.full((config.target_height,config.target_width,3),114,dtype=np.uint8)
    output[top:top+rh,left:left+rw]=cv2.resize(image,(rw,rh),interpolation=cv2.INTER_AREA if scale<1 else cv2.INTER_LINEAR)
    out_mask=None
    if mask is not None:
        if mask.shape!=(height,width):raise ValueError('Image/mask shape mismatch before preprocessing')
        out_mask=np.zeros((config.target_height,config.target_width),dtype=np.uint8)
        out_mask[top:top+rh,left:left+rw]=cv2.resize(mask,(rw,rh),interpolation=cv2.INTER_NEAREST)
    return PreparedSample(output,out_mask,Transform(width=config.target_width,height=config.target_height,
        resized_width=rw,resized_height=rh,pad_left=left,pad_top=top))


def save_pair(sample: PreparedSample, image_path: Path, mask_path: Path) -> None:
    """Save genuine pairs only; RGB PNG plus indexed PNG, with no fake mask path."""
    if sample.mask is None:raise ValueError('Cannot export a segmentation pair without source segmentation')
    image_path.parent.mkdir(parents=True,exist_ok=True);mask_path.parent.mkdir(parents=True,exist_ok=True)
    Image.fromarray(sample.image).save(image_path)
    Image.fromarray(sample.mask).save(mask_path)
