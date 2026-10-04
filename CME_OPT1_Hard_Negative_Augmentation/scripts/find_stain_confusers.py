"""Find annotated textile stain confusers; these are potential failures, not model false positives."""
import csv, hashlib, re, sys
from pathlib import Path
import cv2
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'Preprocessing/scripts'))
from mine_hard_negatives import FIELDS,digest,dhash,write_manifest
root=Path('Hazard_Expansion/content_runtime/combined_dataset')
image_paths={p.stem:p for p in (root/'images/train').glob('*')}
rows=[];groups=set(); hashes=[]
for label in sorted((root/'labels/train').glob('*.txt')):
    if re.search(r'_aug\d+$',label.stem):continue
    family=label.stem.split('.rf.')[0]
    if family in groups:continue
    boxes=[list(map(float,l.split())) for l in label.read_text().splitlines() if l.strip()]
    if not boxes or any(b[0]>=7 for b in boxes):continue
    stains=[b for b in boxes if b[0]==6 and .0025<=b[3]*b[4]<=.65]
    if not stains:continue
    path=image_paths[label.stem];im=cv2.imread(str(path))
    ph=dhash(im);flip=dhash(cv2.flip(im,1))
    if any(min((ph ^ prev).bit_count(),(flip ^ prev).bit_count())<=6 for prev in hashes):continue
    groups.add(family);hashes.append(ph);sha=digest(path)
    rows.append(dict(zip(FIELDS,[f'7-confuser-{sha[:12]}',path.relative_to(root).as_posix(),sha,
         'train','chemical hazard','potential_hard_negative','','','False','',
         'annotated textile stain; visually liquid-like discoloration candidate; no model false-positive claim',
         'false','color_jitter,hsv,chemical_sheen,mosaic','pending','','',f'{ph:016x}'])))
write_manifest(Path('CME_OPT1_Hard_Negative_Augmentation/reports/confuser_candidates.csv'),rows)
print('Independent stain confuser candidates:',len(rows))
