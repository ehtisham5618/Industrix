"""Small actual-data sanity grids and disk-indexed statistics/report export."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Sequence

import cv2
import numpy as np
from PIL import Image,ImageDraw,ImageFont

from .contracts import ClassMapping,ClassStatistics,DatasetConfig,DatasetStatistics,SegmentationSample
from .validation import decode_image,read_annotations

COLORS=((230,70,70),(40,160,225),(50,180,90),(220,155,25),(150,75,220),(235,95,170),(40,170,160))


def statistics(db: sqlite3.Connection, mapping: ClassMapping) -> DatasetStatistics:
    """Aggregate on disk; resolution output is capped at 32 distinct shapes."""
    def scalar(sql: str) -> int:
        return int(db.execute(sql).fetchone()[0] or 0)
    total=scalar('SELECT COUNT(*) FROM samples');valid=scalar('SELECT SUM(source_valid) FROM samples')
    seg=scalar('SELECT SUM(seg_valid) FROM samples');seg_pixels=scalar('SELECT SUM(width*height) FROM samples WHERE seg_valid=1')
    cls=[]
    for cid,name in mapping.names.items():
        row=db.execute('SELECT samples,instances,pixels FROM class_counts WHERE id=?',(cid,)).fetchone()
        ns,ni,pixels=(tuple(row) if row else (0,0,0))
        cls.append(ClassStatistics(class_id=cid,name=name,samples=ns,instances=ni,
            foreground_pixels=pixels if seg else None,area_fraction=pixels/seg_pixels if seg_pixels else None))
    shapes={str(row[0]):int(row[1]) for row in db.execute("SELECT width||'x'||height,COUNT(*) FROM samples WHERE width IS NOT NULL GROUP BY width,height ORDER BY COUNT(*) DESC,width,height LIMIT 32")}
    all_shapes=scalar('SELECT COUNT(*) FROM (SELECT width,height FROM samples WHERE width IS NOT NULL GROUP BY width,height)')
    return DatasetStatistics(total_samples=total,source_valid_samples=valid,invalid_source_samples=total-valid,
        valid_segmentation_samples=seg,boxes_only_samples=scalar("SELECT COUNT(*) FROM samples WHERE kind='box' AND source_valid=1"),
        empty_annotations=scalar('SELECT SUM(empty) FROM samples'),split_counts={s:scalar(f"SELECT COUNT(*) FROM samples WHERE split='{s}'") for s in ('train','val','test')},
        classes=cls,issues={str(r[0]):int(r[1]) for r in db.execute('SELECT code,n FROM issues ORDER BY code')},
        orphan_annotations=scalar("SELECT COUNT(*) FROM files f WHERE kind='annotation' AND NOT EXISTS(SELECT 1 FROM files i WHERE i.kind='image' AND i.split=f.split AND i.stem=f.stem)"),
        duplicate_sample_ids=scalar("SELECT COUNT(*) FROM (SELECT split,stem FROM files WHERE kind='image' GROUP BY split,stem HAVING COUNT(*)>1)"),
        duplicate_hash_groups=scalar('SELECT COUNT(*) FROM (SELECT pixel_sha FROM samples WHERE pixel_sha IS NOT NULL GROUP BY pixel_sha HAVING COUNT(*)>1)'),
        cross_split_hash_groups=scalar('SELECT COUNT(*) FROM (SELECT pixel_sha FROM samples WHERE pixel_sha IS NOT NULL GROUP BY pixel_sha HAVING COUNT(DISTINCT split)>1)'),
        resolution_counts=shapes,unlisted_resolution_groups=max(0,all_shapes-32))


def sanity_grid(config: DatasetConfig, mapping: ClassMapping, rows: Sequence[SegmentationSample], target: Path, segmentation: bool) -> None:
    """Render only supplied source annotations, explicitly distinguishing boxes."""
    width=1000;height=100+len(rows)*280+80
    canvas=Image.new('RGB',(width,height),'white');draw=ImageDraw.Draw(canvas)
    try:font=ImageFont.truetype('DejaVuSans.ttf',15);small=ImageFont.truetype('DejaVuSans.ttf',12)
    except OSError:font=ImageFont.load_default(size=15);small=ImageFont.load_default(size=12)
    title='GENUINE SEGMENTATION ANNOTATIONS' if segmentation else 'REAL SOURCE BOX AUDIT - NOT SEGMENTATION MASKS'
    draw.text((20,14),title,fill='#17344d',font=font)
    draw.text((20,40),'Source is unchanged. Transparent overlay follows only actual annotation geometry.',fill='#526478',font=small)
    for index,row in enumerate(rows):
        image,_=decode_image(config.dataset_root/row.image.path,config)
        parsed=read_annotations(config.dataset_root/str(row.annotation_path),image.shape[1],image.shape[0],config,mapping)
        original=Image.fromarray(image);overlay=original.convert('RGBA');layer=Image.new('RGBA',original.size,(0,0,0,0));ld=ImageDraw.Draw(layer)
        if segmentation and parsed.mask is not None:
            tint=np.zeros((*parsed.mask.shape,4),dtype=np.uint8)
            for cid in mapping.names:tint[parsed.mask==cid+1]=(*COLORS[cid%len(COLORS)],90)
            layer=Image.fromarray(tint)
        else:
            for a in parsed.annotations:
                if a.bbox:
                    x1,y1,x2,y2=a.bbox;box=(round(x1*original.width),round(y1*original.height),round(x2*original.width),round(y2*original.height))
                    ld.rectangle(box,outline=(*COLORS[a.class_id%len(COLORS)],255),width=max(2,original.width//180))
        overlay=Image.alpha_composite(overlay,layer).convert('RGB')
        top=90+index*280
        for picture,x in [(original,20),(overlay,500)]:
            picture.thumbnail((460,230));canvas.paste(picture,(x,top+20))
        label=row.sample_id
        if draw.textlength(label,font=small)>460:
            while draw.textlength(label+'...',font=small)>460:label=label[:-1]
            label+='...'
        draw.text((20,top),label,fill='#17344d',font=small)
        classes=sorted({a.class_id for a in row.annotations})
        draw.text((500,top),' | '.join(mapping.names[c] for c in classes) or 'Explicit empty annotation',fill='#17344d',font=small)
    draw.text((20,height-50),'Legend: '+' | '.join(f'{k}: {v}' for k,v in mapping.names.items()),fill='#526478',font=small)
    target.parent.mkdir(parents=True,exist_ok=True);canvas.save(target)
