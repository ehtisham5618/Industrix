"""Bounded decoding, canonical label normalization and strict geometry checks."""
from __future__ import annotations

import hashlib
import math
import struct
import sys
from decimal import Decimal,InvalidOperation
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray
from PIL import Image, UnidentifiedImageError

from .config import inside
from .contracts import ClassMapping, DatasetConfig, ImageRecord, Issue, Point, SegmentationAnnotation
from .errors import InvalidSampleError
from Preprocessing.scripts.validate_yolo_dataset import validate_label_line

RGBImage = NDArray[np.uint8]
IndexedMask = NDArray[np.uint8]


def open_image(path: Path) -> Image.Image:
    """Use Pillow's native decoder, bypassing Ultralytics' install-on-error hook.

    Another repository test/application may already have imported Ultralytics,
    which globally replaces PIL.Image.open and tries HEIF installation on every
    decode failure. QCI standard formats and corruption handling must stay local.
    This does not import Ultralytics or modify the process-global Pillow function.
    """
    opener=Image.open
    if getattr(opener,'__module__','')=='ultralytics.utils.patches':
        module=sys.modules.get('ultralytics.utils.patches')
        native=getattr(module,'_image_open',None)
        if native is None or getattr(native,'__module__','')!='PIL.Image':
            raise RuntimeError('Installed Ultralytics image wrapper lacks a verified native Pillow decoder')
        opener=native
    return opener(path)


def failure(code: str, stage: str, message: str, error: Exception | None = None) -> InvalidSampleError:
    """Create a bounded structured recoverable failure."""
    return InvalidSampleError(Issue(code=code,stage=stage,message=message[:500],error_type=type(error).__name__ if error else None))


def file_hash(path: Path) -> str:
    """Hash file contents in bounded chunks."""
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def decode_image(path: Path, config: DatasetConfig) -> tuple[RGBImage, ImageRecord]:
    """Check bytes/dimensions before decoding; never apply unlabelled EXIF rotation."""
    try:
        path=inside(path,config.dataset_root)
        if path.stat().st_size>config.max_image_bytes:raise failure('IMAGE_BYTE_LIMIT','image','Encoded image exceeds max_image_bytes')
        with open_image(path) as header:
            width,height=header.size
            if width<1 or height<1 or width*height>config.max_pixels:raise failure('IMAGE_PIXEL_LIMIT','image','Image exceeds the positive pixel budget')
            if getattr(header,'n_frames',1)!=1:raise failure('MULTIFRAME_IMAGE','image','A sample must be a single image')
        # PNG getexif() can decode/close its file. verify() must run on a freshly
        # opened decoder, before metadata access that can force pixel loading.
        with open_image(path) as verification:verification.verify()
        with open_image(path) as source:
            if source.getexif().get(274,1)!=1:raise failure('EXIF_ORIENTATION','image','Normalize image AND annotation orientation explicitly before ingestion')
            # RGB JPEGs dominate the real corpus. Avoid Pillow's redundant
            # full-size RGB->RGB copy while preserving the same decoded pixels.
            rgb=np.array(source if source.mode=='RGB' else source.convert('RGB'),dtype=np.uint8)
        digest=hashlib.sha256(struct.pack('!II',width,height));digest.update(memoryview(rgb).cast('B'))
        return rgb,ImageRecord(path=path.relative_to(config.dataset_root).as_posix(),width=width,height=height,
            sha256=file_hash(path),pixel_sha256=digest.hexdigest())
    except InvalidSampleError:raise
    except (OSError,ValueError,RuntimeError,EOFError,SyntaxError,OverflowError,UnidentifiedImageError,Image.DecompressionBombError) as exc:
        code='IMAGE_READ_ERROR' if isinstance(exc,PermissionError) else 'CORRUPTED_IMAGE'
        raise failure(code,'image',str(exc),exc) from exc


def class_id(token: str, mapping: ClassMapping) -> tuple[int, bool]:
    """Normalize actual repository integer-valued class tokens such as '4.0'."""
    try:
        value=Decimal(token)
        if not value.is_finite() or value<0 or value>=len(mapping.names) or value!=value.to_integral_value():raise ValueError('Unknown/noninteger class ID')
        result=int(value);return result,token!=str(result)
    except (ValueError,InvalidOperation) as exc:raise failure('INVALID_CLASS_ID','annotation',str(exc),exc) from exc


def cross(a: Point, b: Point, c: Point) -> float:
    """Signed two-dimensional orientation."""
    return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])


def segment_intersects(a: Point, b: Point, c: Point, d: Point) -> bool:
    """Detect both crossings and touching nonadjacent polygon edges."""
    values=(cross(a,b,c),cross(a,b,d),cross(c,d,a),cross(c,d,b))
    if values[0]*values[1]<0 and values[2]*values[3]<0:return True
    for value,p,x,y in [(values[0],c,a,b),(values[1],d,a,b),(values[2],a,c,d),(values[3],b,c,d)]:
        if abs(value)<1e-12 and min(x[0],y[0])<=p[0]<=max(x[0],y[0]) and min(x[1],y[1])<=p[1]<=max(x[1],y[1]):return True
    return False


def validate_polygon(points: list[Point], config: DatasetConfig) -> tuple[list[Point], float]:
    """Reject nonfinite, degenerate, repeated or self-intersecting polygons."""
    if points and points[0]==points[-1]:points=points[:-1]
    if not 3<=len(points)<=config.max_polygon_points or len(set(points))!=len(points):
        raise failure('MALFORMED_POLYGON','annotation','Polygon needs distinct vertices within the configured point bound')
    if any(not math.isfinite(x) or not math.isfinite(y) or not 0<=x<=1 or not 0<=y<=1 for x,y in points):
        raise failure('POLYGON_BOUNDS','annotation','Normalized polygon coordinates must be finite and in [0,1]')
    n=len(points)
    for i in range(n):
        for j in range(i+1,n):
            if j==i+1 or (i==0 and j==n-1):continue
            if segment_intersects(points[i],points[(i+1)%n],points[j],points[(j+1)%n]):
                raise failure('SELF_INTERSECTING_POLYGON','annotation','Nonadjacent polygon edges intersect')
    area=abs(sum(points[k][0]*points[(k+1)%n][1]-points[(k+1)%n][0]*points[k][1] for k in range(n)))/2
    if area<=1e-12:raise failure('ZERO_AREA_POLYGON','annotation','Polygon has zero area')
    return points,area


@dataclass
class AnnotationResult:
    """Single-sample annotation buffers; at most one class-index mask."""
    kind: str
    annotations: list[SegmentationAnnotation]
    mask: IndexedMask | None
    warnings: list[str]
    empty: bool


def read_annotations(path: Path, width: int, height: int, config: DatasetConfig, mapping: ClassMapping) -> AnnotationResult:
    """Read the actual YOLO family or explicitly configured class-index PNG."""
    if not path.is_file():raise failure('MISSING_ANNOTATION','annotation','Required annotation is missing')
    try:
        path=inside(path,config.dataset_root)
        limit=config.max_image_bytes if config.annotation_format=='indexed_mask' else config.max_annotation_bytes
        if path.stat().st_size>limit:raise failure('ANNOTATION_BYTE_LIMIT','annotation','Annotation exceeds configured byte limit')
        if config.annotation_format=='indexed_mask':return read_mask(path,width,height,config,mapping)
        lines=path.read_text(encoding='utf-8').splitlines();annotations=[];warnings=[];kinds=set()
        for line in lines:
            if not line.strip():continue
            if len(annotations)>=config.max_instances:raise failure('ANNOTATION_INSTANCE_LIMIT','annotation','Too many annotation instances')
            parts=line.split();cid,changed=class_id(parts[0],mapping)
            if changed and 'INTEGER_CLASS_TOKEN_NORMALIZED' not in warnings:warnings.append('INTEGER_CLASS_TOKEN_NORMALIZED')
            if len(parts)==5:
                normalized=' '.join([str(cid),*parts[1:]])
                ok,reason=validate_label_line(normalized,len(mapping.names))
                if not ok:raise failure('MALFORMED_BOX','annotation',reason)
                xc,yc,w,h=map(float,parts[1:])
                box=(max(0.,xc-w/2),max(0.,yc-h/2),min(1.,xc+w/2),min(1.,yc+h/2))
                if box!=(xc-w/2,yc-h/2,xc+w/2,yc+h/2):warnings.append('ROUNDING_EDGE_CLIPPED')
                annotations.append(SegmentationAnnotation(class_id=cid,kind='box',bbox=box));kinds.add('box')
            elif len(parts)>=7 and len(parts)%2==1:
                if (len(parts)-1)//2>config.max_polygon_points:raise failure('POLYGON_POINT_LIMIT','annotation','Too many polygon points')
                values=[float(v) for v in parts[1:]];points,area=validate_polygon(list(zip(values[::2],values[1::2])),config)
                annotations.append(SegmentationAnnotation(class_id=cid,kind='polygon',polygon=points,area_normalized=area,
                    bbox=(min(p[0] for p in points),min(p[1] for p in points),max(p[0] for p in points),max(p[1] for p in points))));kinds.add('polygon')
            else:raise failure('MALFORMED_ANNOTATION','annotation','YOLO line must have five box fields or >=7 odd polygon fields')
        if len(kinds)>1:raise failure('MIXED_ANNOTATION_FORMAT','annotation','Boxes and polygons cannot form one segmentation sample')
        if not annotations and not config.allow_empty_annotations:raise failure('EMPTY_ANNOTATION','annotation','Empty annotations are not allowed by this config')
        if not annotations and config.empty_yolo_annotation_kind=='box':
            return AnnotationResult('box',[],None,warnings,True)
        if kinds=={'box'}:return AnnotationResult('box',annotations,None,warnings,False)
        mask=rasterize(annotations,width,height)
        return AnnotationResult('polygon' if annotations else 'empty',annotations,mask,warnings,not annotations)
    except InvalidSampleError:raise
    except (OSError,ValueError,UnicodeError,cv2.error) as exc:
        code='ANNOTATION_READ_ERROR' if isinstance(exc,PermissionError) else 'MALFORMED_ANNOTATION'
        raise failure(code,'annotation',str(exc),exc) from exc


def rasterize(annotations: list[SegmentationAnnotation], width: int, height: int) -> IndexedMask:
    """Source ID k maps to mask k+1; different-class overlaps are rejected."""
    mask=np.zeros((height,width),dtype=np.uint8)
    for annotation in annotations:
        layer=np.zeros_like(mask)
        points=np.rint(np.asarray(annotation.polygon)*np.array([width,height])).astype(np.int32)
        points[:,0]=points[:,0].clip(0,width-1);points[:,1]=points[:,1].clip(0,height-1)
        cv2.fillPoly(layer,[points],1)
        active=layer.astype(bool);label=annotation.class_id+1
        if np.any(active&(mask!=0)&(mask!=label)):raise failure('OVERLAPPING_CLASSES','segmentation','Ambiguous different-class polygon overlap')
        if not np.any(active):raise failure('EMPTY_RASTERIZATION','segmentation','Nonempty polygon produced no foreground')
        annotation.foreground_pixels=int(np.count_nonzero(active));mask[active]=label
    return mask


def read_mask(path: Path, width: int, height: int, config: DatasetConfig, mapping: ClassMapping) -> AnnotationResult:
    """Validate actual indexed PNG dimensions/values before any interpolation."""
    try:
        with open_image(path) as source:
            if source.format!='PNG':raise failure('MASK_NOT_PNG','segmentation','Indexed-mask adapter requires actual lossless PNG content')
            if source.size!=(width,height):raise failure('DIMENSION_MISMATCH','segmentation','Image and mask dimensions differ')
            if source.mode not in ('L','P','I','I;16'):raise failure('MASK_NOT_INDEXED','segmentation','Mask must contain class indices, not RGB colors')
            source.verify()
        with open_image(path) as source:mask=np.array(source)
        values=np.unique(mask)
        if any(int(v)<0 or int(v)>len(mapping.names) for v in values):raise failure('INVALID_MASK_CLASS','segmentation','Expected background 0 and source class IDs + 1')
        mask=mask.astype(np.uint8);annotations=[]
        for value in values:
            if value:annotations.append(SegmentationAnnotation(class_id=int(value)-1,kind='indexed_mask',foreground_pixels=int(np.count_nonzero(mask==value))))
        if not annotations and not config.allow_empty_annotations:raise failure('EMPTY_ANNOTATION','segmentation','Empty masks are disallowed')
        return AnnotationResult('indexed_mask',annotations,mask,[],not annotations)
    except InvalidSampleError:raise
    except (OSError,ValueError,EOFError,SyntaxError,RuntimeError,UnidentifiedImageError) as exc:raise failure('CORRUPTED_MASK','segmentation',str(exc),exc) from exc
