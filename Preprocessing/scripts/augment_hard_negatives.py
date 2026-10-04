"""Deterministic train-only augmentation of reviewed, failure-aware samples."""
import argparse
import csv
import json
import shutil
from pathlib import Path

import cv2
import numpy as np
import yaml

from mine_hard_negatives import digest, read_labels, source_family
from validate_yolo_dataset import validate_label_line, validate_dataset

STRATEGIES=('color_jitter','hsv','chemical_sheen','mosaic','smoke_overlay')


def photometric(image, strategy, rng, boxes=(), smoke_id=None):
    """Geometry is preserved; overlay only inside an existing annotated smoke box."""
    out=image.astype(np.float32)
    if strategy=='color_jitter':
        out=(out-127.5)*rng.uniform(.85,1.15)+127.5+rng.uniform(-18,18)
        hsv=cv2.cvtColor(np.clip(out,0,255).astype(np.uint8),cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[:,:,1]*=rng.uniform(.85,1.15)
        hsv[:,:,0]=(hsv[:,:,0]+rng.uniform(-3,3))%180
        out=cv2.cvtColor(np.clip(hsv,0,255).astype(np.uint8),cv2.COLOR_HSV2BGR)
    elif strategy=='hsv':
        hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[:,:,0]=(hsv[:,:,0]+rng.uniform(-5,5))%180
        hsv[:,:,1]*=rng.uniform(.75,1.15); hsv[:,:,2]*=rng.uniform(.85,1.15)
        out=cv2.cvtColor(np.clip(hsv,0,255).astype(np.uint8),cv2.COLOR_HSV2BGR)
    elif strategy=='chemical_sheen':
        h,w=image.shape[:2]; yy,xx=np.mgrid[:h,:w]
        band=np.exp(-((yy/h-rng.uniform(.45,.85))/.10)**2)*(.6+.4*np.cos(xx/w*3))
        ir_like=bool(rng.integers(2))
        tint=np.array([.95,1.0,.9]) if not ir_like else np.ones(3)
        if ir_like:
            gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)[:,:,None]
            out=.35*out+.65*gray
        out+=band[:,:,None]*rng.uniform(8,24)*tint
    elif strategy=='smoke_overlay':
        smoke=[b for b in boxes if int(b[0])==smoke_id]
        if not smoke: raise ValueError('Smoke overlay requires a real existing smoke annotation')
        _,xc,yc,bw,bh=smoke[int(rng.integers(len(smoke)))]; h,w=image.shape[:2]
        x1,y1=max(0,int((xc-bw/2)*w)),max(0,int((yc-bh/2)*h))
        x2,y2=min(w,int((xc+bw/2)*w)),min(h,int((yc+bh/2)*h))
        if x2-x1<4 or y2-y1<4: raise ValueError('Smoke region is too small')
        noise=cv2.resize(rng.uniform(0,1,(8,8)).astype(np.float32),(x2-x1,y2-y1))
        yy,xx=np.mgrid[:y2-y1,:x2-x1]
        mask=np.sin(np.pi*xx/(x2-x1))**2*np.sin(np.pi*yy/(y2-y1))**2
        alpha=(noise*mask*rng.uniform(.12,.28))[:,:,None]
        out[y1:y2,x1:x2]=out[y1:y2,x1:x2]*(1-alpha)+210*alpha
    else: raise ValueError(strategy)
    return np.clip(out,0,255).astype(np.uint8)


def mosaic(images, labels, size=640, min_pixels=2):
    if len(images)!=4 or len(labels)!=4 or size%2: raise ValueError('Mosaic needs four images and even size')
    out=np.zeros((size,size,3),np.uint8); result=[]; half=size//2
    for index,(image,boxes) in enumerate(zip(images,labels)):
        ox=(index%2)*half; oy=(index//2)*half
        out[oy:oy+half,ox:ox+half]=cv2.resize(image,(half,half))
        for cls,x,y,w,h in boxes:
            x1=np.clip((x-w/2)*half,0,half)+ox; x2=np.clip((x+w/2)*half,0,half)+ox
            y1=np.clip((y-h/2)*half,0,half)+oy; y2=np.clip((y+h/2)*half,0,half)+oy
            if x2-x1>=min_pixels and y2-y1>=min_pixels:
                result.append([cls,(x1+x2)/2/size,(y1+y2)/2/size,(x2-x1)/size,(y2-y1)/size])
    return out,result


def safe_source(dataset,row):
    path=(dataset/row['source_image']).resolve()
    path.relative_to((dataset/'images/train').resolve())
    if row['split']!='train': raise ValueError('Only training sources permitted')
    if digest(path)!=row['source_sha256']: raise ValueError('Source changed since mining')
    return path


def snapshot(dataset, splits=('val','test')):
    return {p.relative_to(dataset).as_posix():digest(p)
            for split in splits for kind in ('images','labels')
            for p in sorted((dataset/kind/split).glob('*')) if p.is_file()}


def quality(image, labels, nc):
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    if gray.mean()<8 or gray.mean()>247 or np.mean(gray<3)>.98 or np.mean(gray>252)>.98:
        raise ValueError('Extreme brightness output rejected')
    for b in labels:
        line=f'{int(b[0])} '+ ' '.join(f'{v:.8f}' for v in b[1:])
        valid,reason=validate_label_line(line,nc)
        if not valid: raise ValueError(reason)
        if b[3]*image.shape[1]<2 or b[4]*image.shape[0]<2: raise ValueError('Unusable tiny box')


def qualifying(rows):
    # Count unique independently reviewed real negative source images, never derivatives or positives.
    accepted={r['source_sha256']:r for r in rows if r['failure_type'] in ('hard_negative_candidate','potential_hard_negative')
              and r['verification_status']=='verified' and r['verification_evidence'].strip()
              and r['reviewer'].strip() and r['ground_truth_present'].lower()=='false'
              and r['selected_for_augmentation'].lower()=='true'}
    return accepted


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dataset',type=Path,required=True); p.add_argument('--output',type=Path,required=True)
    p.add_argument('--manifest',type=Path,required=True); p.add_argument('--reports',type=Path,required=True)
    p.add_argument('--seed',type=int,default=42); p.add_argument('--count',type=int,default=150)
    p.add_argument('--version',default='combined-12class-v2-hardnegative')
    p.add_argument('--target-classes',nargs='+',default=['chemical hazard','smoke'])
    p.add_argument('--strategies',nargs='+',choices=STRATEGIES,default=list(STRATEGIES))
    p.add_argument('--probabilities',nargs='+',type=float,help='Weights for strategies, same order')
    a=p.parse_args(); dataset=a.dataset.resolve(); output=a.output.resolve()
    if output==dataset or output.is_relative_to(dataset) or dataset.is_relative_to(output):
        raise ValueError('Output must be separate from original dataset')
    if output.exists(): raise FileExistsError('Refusing to overwrite an existing output dataset')
    if a.count<=0: raise ValueError('count must be positive')
    cfg=yaml.safe_load((dataset/'data.yaml').read_text()); names=cfg['names']
    if isinstance(names,dict): names=[names[i] for i in range(len(names))]
    target_ids=[names.index(n) for n in a.target_classes]
    if len(names)!=12: raise ValueError('Expected 12 classes')
    with a.manifest.open(encoding='utf-8-sig',newline='') as f: all_rows=list(csv.DictReader(f))
    rows=[r for r in all_rows if r['selected_for_augmentation'].lower()=='true'
          and r['target_class'] in a.target_classes and r['verification_status']=='verified'
          and r['verification_evidence'].strip() and r['reviewer'].strip()]
    if a.count<len(rows): raise ValueError('count must cover every selected independently reviewed source')
    if not rows: raise ValueError('No reviewed and explicitly selected samples; review mining manifest first')
    eval_sources=[p for split in ("val","test") for p in (dataset/"images"/split).glob("*") if p.is_file()]
    eval_families={source_family(p) for p in eval_sources}
    eval_hashes={digest(p) for p in eval_sources}
    for row in rows:
        if source_family(row["source_image"]) in eval_families or row["source_sha256"] in eval_hashes:
            raise ValueError("Selected source overlaps evaluation image/family")
        path=safe_source(dataset,row); boxes=read_labels(dataset/'labels/train'/f'{path.stem}.txt')
        has_target=any(int(b[0])==names.index(row['target_class']) for b in boxes)
        if row['failure_type'] in ('hard_negative_candidate','potential_hard_negative') and (has_target or row['ground_truth_present'].lower()!='false'):
            raise ValueError('Negative selection conflicts with target annotations')
    if not validate_dataset(dataset): raise ValueError('Baseline integrity failed; preserve and report source issues first')
    source_before=snapshot(dataset,('train','val','test'))
    eval_before=snapshot(dataset)
    rng=np.random.default_rng(a.seed)
    weights=np.array(a.probabilities if a.probabilities else [1]*len(a.strategies),float)
    if len(weights)!=len(a.strategies) or not np.isfinite(weights).all() or (weights<0).any() or weights.sum()<=0:
        raise ValueError('Invalid strategy weights')
    weights/=weights.sum()
    shutil.copytree(dataset,output)
    cfg['path']=str(output); cfg['names']=names
    (output/'data.yaml').write_text(yaml.safe_dump(cfg,sort_keys=False))
    known={digest(p) for p in (output/'images/train').glob('*') if p.is_file()}
    additions=[]; attempts=0
    while len(additions)<a.count:
        attempts+=1
        if attempts>a.count*30: raise RuntimeError('Cannot satisfy requested count with eligible strategies/QC')
        row=rows[len(additions)] if len(additions)<len(rows) else rows[int(rng.integers(len(rows)))]; path=safe_source(dataset,row)
        boxes=read_labels(dataset/'labels/train'/f'{path.stem}.txt')
        allowed=[s for s in row['augmentation_strategy'].split(',') if s in a.strategies]
        allowed=[s for s in allowed if not (s=='smoke_overlay' and not any(int(b[0])==names.index('smoke') for b in boxes))]
        if not allowed: raise ValueError('Selected source has no eligible configured strategy')
        subweights=np.array([weights[a.strategies.index(s)] for s in allowed])
        if subweights.sum()<=0: raise ValueError('No positive probability for eligible strategies')
        strategy=str(rng.choice(allowed,p=subweights/subweights.sum()))
        if strategy=='smoke_overlay' and not any(int(b[0])==names.index('smoke') for b in boxes): continue
        if strategy=='chemical_sheen' and row['target_class']!='chemical hazard': continue
        seed=int(rng.integers(0,2**32)); local=np.random.default_rng(seed); sources=[row]
        image=cv2.imread(str(path)); label_bytes=(dataset/'labels/train'/f'{path.stem}.txt').read_bytes()
        if strategy=='mosaic':
            sources=[row]+[rows[int(local.integers(len(rows)))] for _ in range(3)]
            paths=[safe_source(dataset,r) for r in sources]
            image,boxes=mosaic([cv2.imread(str(p)) for p in paths],
                [read_labels(dataset/'labels/train'/f'{p.stem}.txt') for p in paths])
            label_bytes=('\n'.join(f'{int(b[0])} '+' '.join(f'{v:.8f}' for v in b[1:]) for b in boxes)+'\n').encode()
        else: image=photometric(image,strategy,local,boxes,names.index('smoke'))
        try: quality(image,boxes,len(names))
        except ValueError: continue
        stem=f'cmeopt1_{len(additions):05d}_{seed}'; dest=output/'images/train'/f'{stem}.png'
        if not cv2.imwrite(str(dest),image): raise IOError(dest)
        sha=digest(dest)
        if sha in known: dest.unlink(); continue
        known.add(sha)
        (output/'labels/train'/f'{stem}.txt').write_bytes(label_bytes)
        additions.append({'source_image':json.dumps([r['source_image'] for r in sources]),
            'source_sha256':json.dumps([r['source_sha256'] for r in sources]),'output_image':dest.relative_to(output).as_posix(),
            'output_sha256':sha,'split':'train','target_category':row['target_class'],
            'sample_type':'mosaic' if strategy=='mosaic' else 'synthetic_overlay' if strategy=='smoke_overlay' else 'augmented_real',
            'augmentation_type':strategy,'seed':seed,'annotation_count':len(boxes),
            'target_annotations':sum(int(b[0]) in target_ids for b in boxes),'verified':True,
            'source_failure_type':row['failure_type'],'notes':'Derived from reviewed sources; does not count as independently mined negative'})
    assert snapshot(output)==eval_before, 'Evaluation data changed'
    assert snapshot(dataset,('train','val','test'))==source_before, 'Source dataset changed'
    a.reports.mkdir(parents=True,exist_ok=True)
    with (a.reports/'augmentation_manifest.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=list(additions[0])); writer.writeheader(); writer.writerows(additions)
    used={sha for addition in additions for sha in json.loads(addition['source_sha256'])}
    q=qualifying([r for r in rows if r['source_sha256'] in used])
    summary={'version':a.version,'source_version':'combined_dataset.zip','seed':a.seed,
        'source_dataset':str(dataset),'output_dataset':str(output),'added_images':len(additions),
        'verified_chemical_examples':sum(r['target_class']=='chemical hazard' for r in q.values()),
        'verified_smoke_examples':sum(r['target_class']=='smoke' for r in q.values()),
        'verified_potential_confuser_images':len({r['source_sha256'] for r in rows if r['failure_type']=='potential_hard_negative' and r['source_sha256'] in used}),
        'hard_positive_images':len({r['source_sha256'] for r in rows if r['failure_type']=='hard_positive' and r['source_sha256'] in used}),
        'verified_combined_qualifying_examples':len(q),'requirement_150':'PASS' if len(q)>=150 else 'FAIL',
        'verified_observed_negative_images':sum(r['failure_type']=='hard_negative_candidate' for r in q.values()),
        'verified_potential_negative_images':sum(r['failure_type']=='potential_hard_negative' for r in q.values()),
        'count_definition':'Unique reviewed real negative source image hashes used in train augmentation: observed errors and verified visual confusers under task section 13 (causes or could cause); derivatives and positives excluded',
        'evaluation_unchanged':True,'source_preserved':True,'validation_status':'pending'}
    passed=validate_dataset(output,report=a.reports/'after/validation.json')
    summary['validation_status']='PASS' if passed else 'FAIL'
    (a.reports/'augmentation_summary.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,indent=2))
    if not passed: raise SystemExit(1)

if __name__=='__main__': main()
