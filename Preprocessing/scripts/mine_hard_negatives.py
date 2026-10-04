"""Mine current-detector failures. Predictions are candidates, never ground truth."""
import argparse
import csv
import hashlib
import json
import re
from pathlib import Path

import cv2
import numpy as np
import yaml

FIELDS = ['sample_id','source_image','source_sha256','split','target_class','failure_type',
          'predicted_class','confidence','ground_truth_present','prediction_box','reason',
          'selected_for_augmentation','augmentation_strategy','verification_status','verification_evidence',
          'reviewer','perceptual_hash']


def source_family(path):
    return re.sub(r"_aug\d+$", "", Path(path).stem).split(".rf.")[0]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dhash(image):
    gray = cv2.resize(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), (9,8))
    return sum(int(v) << i for i,v in enumerate((gray[:,1:] > gray[:,:-1]).ravel()))


def read_labels(path):
    return [list(map(float,line.split())) for line in path.read_text().splitlines() if line.strip()]


def iou(a,b):
    x1,y1 = max(a[0],b[0]),max(a[1],b[1])
    x2,y2 = min(a[2],b[2]),min(a[3],b[3])
    inter=max(0,x2-x1)*max(0,y2-y1)
    return inter/max(1e-12,(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-inter)


def xyxy(label):
    _,x,y,w,h=label
    return [x-w/2,y-h/2,x+w/2,y+h/2]


def write_manifest(path, rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=FIELDS); writer.writeheader(); writer.writerows(rows)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dataset',type=Path,required=True)
    p.add_argument('--model',type=Path,default=Path('Backend/best.pt'))
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--confidence',type=float,default=.15)
    p.add_argument('--imgsz',type=int,default=640)
    p.add_argument('--limit',type=int,default=0,help='0 scans all training images')
    p.add_argument('--threads',type=int,default=4)
    p.add_argument('--near-distance',type=int,default=4)
    args=p.parse_args()
    import torch
    from ultralytics import YOLO
    torch.set_num_threads(args.threads)
    cfg=yaml.safe_load((args.dataset/'data.yaml').read_text()); names=cfg['names']
    if isinstance(names,dict): names=[names[i] for i in range(len(names))]
    assert len(names)==12, 'Expected 12-class source dataset'
    targets=[i for i,n in enumerate(names) if n.lower() in ('chemical hazard','chemical leak','smoke')]
    assert len(targets)==2, 'Chemical and smoke names must resolve exactly'
    model=YOLO(str(args.model))
    assert [model.names[i] for i in range(len(model.names))]==names, 'Model/dataset mapping mismatch'
    files=sorted((args.dataset/'images/train').glob('*'))
    files=[f for f in files if f.suffix.lower() in {'.jpg','.jpeg','.png','.bmp','.webp'}]
    if args.limit: files=files[:args.limit]
    rows=[]; seen={}; exact=set(); rejected=0
    for index,path in enumerate(files):
        image=cv2.imread(str(path)); sha=digest(path); ph=dhash(image)
        labels=read_labels(args.dataset/'labels/train'/f'{path.stem}.txt')
        result=model.predict(image,conf=args.confidence,imgsz=args.imgsz,device='cpu',verbose=False)[0]
        predictions=[]
        for box in result.boxes:
            cls=int(box.cls.item())
            if cls in targets: predictions.append((cls,float(box.conf.item()),box.xyxyn[0].tolist()))
        for cls in targets:
            truth=[xyxy(l) for l in labels if int(l[0])==cls]
            preds=[(conf,b) for c,conf,b in predictions if c==cls]
            failures=[]
            for conf,b in preds:
                if not any(iou(b,t)>=.3 for t in truth):
                    failures.append(('hard_negative_candidate' if not truth else 'unmatched_prediction',conf,b))
            for t in truth:
                matches=[conf for conf,b in preds if iou(b,t)>=.3]
                if not matches or max(matches)<.4:
                    failures.append(('hard_positive',max(matches,default=0),t))
            if not failures: continue
            kind,conf,box=max(failures,key=lambda f: f[1])
            # Deduplicate whole images within each target/failure category, never count frames twice.
            key=(cls,kind); group=seen.setdefault(key,[])
            if (key,sha) in exact: continue
            if any((ph ^ prev).bit_count()<=args.near_distance for prev in group):
                rejected+=1; continue
            exact.add((key,sha)); group.append(ph)
            rows.append(dict(zip(FIELDS,[f'{cls}-{sha[:16]}',path.relative_to(args.dataset).as_posix(),sha,
                'train',names[cls],kind,names[cls] if conf else '',conf,bool(truth),json.dumps(box),
                'unmatched target prediction; absence needs visual/source verification' if kind!='hard_positive' else 'missed or low-confidence annotated target',
                'false','chemical_sheen' if cls!=names.index('smoke') else 'hsv',
                'pending' if kind!='hard_positive' else 'annotation_supported',
                '' if kind!='hard_positive' else 'existing YOLO box supports positive presence', '',f'{ph:016x}'])))
        if (index+1)%50==0:
            print(f'Scanned {index+1}/{len(files)}; candidates={len(rows)}',flush=True)
            write_manifest(args.output,rows)
    rows.sort(key=lambda r: (-float(r['confidence']),r['sample_id']))
    write_manifest(args.output,rows)
    metadata={'model':str(args.model),'model_sha256':digest(args.model),'model_version':'cme1-expanded-12class-v1',
              'dataset':str(args.dataset),'images_scanned':len(files),'confidence':args.confidence,'imgsz':args.imgsz,
              'near_distance':args.near_distance,'deduplicated_candidates':len(rows),'near_duplicates_rejected':rejected,
              'verified_hard_negatives':0,'note':'Prediction/annotation disagreement does not prove target absence.'}
    args.output.with_suffix('.json').write_text(json.dumps(metadata,indent=2))
    print(json.dumps(metadata,indent=2))

if __name__=='__main__': main()
