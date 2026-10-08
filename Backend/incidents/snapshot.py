"""Native-resolution unannotated JPEG crop; no enlargement or remote assets."""
import hashlib
import math
import os
import re
import tempfile
from pathlib import Path

def crop_bounds(frame,bbox,padding=.10,min_context=64):
    h,w=frame.shape[:2]
    values=[float(bbox[k]) for k in ('x1','y1','x2','y2')]
    if not all(math.isfinite(v) for v in values):raise ValueError('Nonfinite bounding box')
    x1,y1,x2,y2=values
    if x2<=x1 or y2<=y1:raise ValueError('Reversed or empty bounding box')
    x1,y1,x2,y2=max(0,x1),max(0,y1),min(w,x2),min(h,y2)
    if x2<=x1 or y2<=y1:raise ValueError('Bounding box does not intersect frame')
    if not 0<=padding<=1:raise ValueError('Crop padding must be between zero and one')
    cx,cy=(x1+x2)/2,(y1+y2)/2
    width,height=max(min_context,(x2-x1)*(1+2*padding)),max(min_context,(y2-y1)*(1+2*padding))
    left=max(0,min(w-min(width,w),cx-width/2));top=max(0,min(h-min(height,h),cy-height/2))
    return (max(0,math.floor(left)),max(0,math.floor(top)),min(w,math.ceil(left+width)),min(h,math.ceil(top+height)))

def write_snapshot(directory,incident_id,camera,class_name,frame,bbox,padding=.10):
    import cv2
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    slug=lambda text:re.sub('[^a-zA-Z0-9_-]+','_',text).strip('_')[:50] or 'unknown'
    filename=f'{incident_id}_{slug(camera)}_{slug(class_name)}.jpg'
    bounds=crop_bounds(frame,bbox,padding);x1,y1,x2,y2=bounds
    crop=frame[y1:y2,x1:x2]
    ok,jpeg=cv2.imencode('.jpg',crop,[cv2.IMWRITE_JPEG_QUALITY,95])
    if not ok:raise OSError('JPEG encoding failed')
    data=jpeg.tobytes();temporary=None
    try:
        with tempfile.NamedTemporaryFile(dir=directory,suffix='.tmp',delete=False) as fh:
            temporary=Path(fh.name);fh.write(data);fh.flush();os.fsync(fh.fileno())
        os.replace(temporary,directory/filename)
    finally:
        if temporary and temporary.exists():temporary.unlink()
    return dict(snapshot_path=filename,snapshot_status='ready',snapshot_error=None,
                snapshot_sha256=hashlib.sha256(data).hexdigest(),crop_rect=__import__('json').dumps(bounds),
                snapshot_width=crop.shape[1],snapshot_height=crop.shape[0])
