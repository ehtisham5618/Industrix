"""Add visually reviewed, licensed real negatives to a separate training source dataset.

Review decisions must identify a real confusing region and establish absence of ALL
12 classes before an empty YOLO label is written. Uncertain scenes stay excluded.
"""
import argparse,csv,json,re,shutil,sys
from pathlib import Path
import cv2,yaml
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'Preprocessing/scripts'))
from mine_hard_negatives import digest,dhash,write_manifest
from augment_hard_negatives import snapshot

def read_csv(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def event_key(record):
    """Conservative capture-day/author and filename-series guards supplement visual review."""
    date=record['date_original'][:10]
    if re.match(r'\d{4}-\d{2}-\d{2}',date) and record['artist_html']:
        return record['artist_html']+'|'+date
    title=re.sub(r'\.(jpg|jpeg|png)$','',record['title'],flags=re.I)
    title=re.sub(r'\([^)]*\d[^)]*\)','',title)
    title=re.sub(r'(?<![a-z])\d+(?![a-z])','',title,flags=re.I)
    title=re.sub(r'[-_ ]+[a-z]$','',title,flags=re.I)
    return re.sub(r'\W+',' ',title).strip().lower()

def credit_key(record):
    # "Own work" and author homepages describe attribution, not a single capture.
    # Only direct photograph identifiers can establish duplicate source provenance.
    match=re.search(r'https?://(?:www\.)?(?:flickr\.com/photos/[^/]+/\d+|geograph\.org\.uk/photo/\d+)',record['credit_html'])
    return match.group(0) if match else ''

def reviewed_region(decision,sha):
    if decision.get('reviewed_sha256')!=sha:raise ValueError('Reference differs from visually reviewed bytes')
    if decision['all_classes_absent'].lower()!='true' or not decision['evidence'].strip() or not decision['reviewer'].strip():
        raise ValueError('Explicit semantic review is required for empty-label negatives')
    box=json.loads(decision['negative_region'])
    if len(box)!=4 or not 0<=box[0]<box[2]<=1 or not 0<=box[1]<box[3]<=1:raise ValueError('Invalid reviewed region')
    return box

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dataset',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--cache',type=Path,default=Path('CME_OPT1_Hard_Negative_Augmentation/runtime/reference_candidates'))
    p.add_argument('--reports',type=Path,default=Path('CME_OPT1_Hard_Negative_Augmentation/reports'))
    a=p.parse_args();r=a.reports;original=a.dataset.resolve();out=a.output.resolve()
    if out.exists() or out==original or out.is_relative_to(original) or original.is_relative_to(out):
        raise ValueError('Require a new separate output dataset')
    candidates={v['sample_id']:v for v in read_csv(r/'reference_candidates.csv')}
    provenance={v['sample_id']:v for v in read_csv(r/'reference_provenance.csv')}
    decisions=read_csv(r/'reference_review_decisions.csv')
    existing=read_csv(r/'reviewed_selection.csv')
    # Evaluation is never mined or imported. Screen against exact and perceptual overlap.
    eval_hashes=set();eval_ph=[]
    for split in ('val','test'):
        for path in (original/'images'/split).glob('*'):
            if not path.is_file():continue
            eval_hashes.add(digest(path));im=cv2.imread(str(path))
            eval_ph.extend((dhash(im),dhash(cv2.flip(im,1))))
    seen_sha={v['source_sha256'] for v in existing};seen_ph=[];seen_events=set();seen_credit=set()
    for v in existing:
        image=cv2.imread(str(original/v['source_image']))
        seen_ph.extend((dhash(image),dhash(cv2.flip(image,1))))
    selected=[];rejected=[]
    for decision in decisions:
        if decision['decision']!='accept':continue
        row=dict(candidates[decision['sample_id']]);record=provenance[row['sample_id']]
        path=(a.cache/row['source_image']).resolve();path.relative_to((a.cache/'images/train').resolve())
        sha=digest(path)
        box=reviewed_region(decision,sha)
        if sha!=row['source_sha256'] or sha!=record['source_sha256']:raise ValueError('Reference source changed')
        license=record['license']
        if not (license.startswith(('CC BY ','CC BY-SA ')) or license in ('CC0','Public domain')):
            raise ValueError('Reference license was not approved')
        image=cv2.imread(str(path));ph=[dhash(image),dhash(cv2.flip(image,1))];key=event_key(record)
        reason=''
        if sha in eval_hashes or any((p^q).bit_count()<=4 for p in ph for q in eval_ph): reason='evaluation exact/perceptual overlap'
        elif sha in seen_sha or any((p^q).bit_count()<=6 for p in ph for q in seen_ph): reason='selected exact/perceptual near duplicate'
        elif key in seen_events:reason='same capture day/author or filename series'
        elif credit_key(record) and credit_key(record) in seen_credit:reason='same original photograph URL'
        if reason:
            rejected.append({'sample_id':row['sample_id'],'reason':reason});continue
        seen_sha.add(sha);seen_ph.extend(ph);seen_events.add(key)
        if credit_key(record):seen_credit.add(credit_key(record))
        row.update(ground_truth_present='False',prediction_box=json.dumps(box),reason=decision['evidence'],
            selected_for_augmentation='true',verification_status='verified',reviewer=decision['reviewer'],
            verification_evidence=decision['evidence']+'; source description/license: '+record['description_url'])
        selected.append(row)
    if not selected:raise ValueError('No reviewed independent references remain')
    print(f'Independent reviewed references after audit: {len(selected)}; excluded duplicates: {len(rejected)}',flush=True)
    before=snapshot(original,('train','val','test'));shutil.copytree(original,out)
    cfg=yaml.safe_load((out/'data.yaml').read_text());cfg['path']=str(out)
    (out/'data.yaml').write_text(yaml.safe_dump(cfg,sort_keys=False))
    for row in selected:
        shutil.copy2(a.cache/row['source_image'],out/row['source_image'])
        (out/'labels/train'/f'{Path(row["source_image"]).stem}.txt').write_bytes(b'')
    assert all(digest(out/p)==sha for p,sha in before.items())
    assert snapshot(original)==snapshot(out)
    write_manifest(r/'reviewed_selection_v3.csv',existing+selected)
    write_manifest(r/'reference_ingestion_manifest.csv',selected)
    (r/'reference_deduplication.json').write_text(json.dumps({'accepted':len(selected),'rejected':rejected,
        'perceptual_distance_selected':6,'perceptual_distance_evaluation':4,
        'event_policy':'one capture day per author or one normalized filename series',
        'all_original_bytes_preserved':True,'evaluation_unchanged':True},indent=2))
    print(json.dumps({'ingested_training_only':len(selected),'excluded_duplicates':len(rejected),'output':str(out)}))

if __name__=='__main__':main()
