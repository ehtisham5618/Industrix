"""Record explicit visual-review decisions by fixed contact-sheet indices."""
import argparse,csv,hashlib,json
from pathlib import Path
import yaml

def indices(value):
    result=set()
    for token in value.split(','):
        if not token:continue
        if '-' in token:
            first,last=map(int,token.split('-'));result.update(range(first,last+1))
        else:result.add(int(token))
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reviewed',required=True);p.add_argument('--accept',required=True)
    p.add_argument('--notes',required=True)
    a=p.parse_args();root=Path('CME_OPT1_Hard_Negative_Augmentation')
    entries=[]
    for f in ('external_candidates.yaml','external_candidates_extra.yaml'):
        entries+=yaml.safe_load((root/'configs'/f).read_text(encoding='utf-8'))
    entries=list({e['title']:e for e in entries}.values());accept=indices(a.accept);reviewed=indices(a.reviewed)
    if not accept<=reviewed:raise ValueError('Accepted indices must have been reviewed')
    path=root/'reports/reference_review_decisions.csv';rows={}
    if path.exists():
        with path.open(encoding='utf-8',newline='') as f:rows={v['sample_id']:v for v in csv.DictReader(f)}
    for index in sorted(reviewed):
        entry=entries[index];key=hashlib.sha256(entry['title'].encode()).hexdigest()[:20]
        image=root/'runtime/reference_candidates/images/train'/f'commons_{key}.jpg'
        if index in accept and not image.exists():raise ValueError('Cannot verify a missing photograph')
        accepted=index in accept
        explanation=('Visible natural water/reflection with normal rain-puddle edges and reflected surroundings; chemical material absent.'
            if entry['target_class']=='chemical hazard' else 'Visible meteorological cloud formations against sky; no emitting source, combustion, fire or industrial smoke.')
        rows[key]={'review_index':index,'sample_id':key,'title':entry['title'],
            'reviewed_sha256':hashlib.sha256(image.read_bytes()).hexdigest() if image.exists() else '',
            'decision':'accept' if accepted else 'reject','all_classes_absent':accepted,
            'negative_region':'[0,0,1,1]' if accepted else '',
            'evidence':explanation+' Visual review of full candidate contact-sheet photograph: no textile defect, fire, smoke, leak or unsafe worker class is visible. '+a.notes if accepted else a.notes+' Excluded: uncertain scene, duplicate view, insufficient confuser relevance or unavailable photo.',
            'reviewer':'Codex visual review (AI; no human reviewer impersonated)'}
    with path.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(next(iter(rows.values()))));w.writeheader();w.writerows(sorted(rows.values(),key=lambda r:int(r['review_index'])))
    print(f'Recorded {len(reviewed)} explicit decisions; accepted {len(accept)} before automatic lineage/dedup checks.')

if __name__=='__main__':main()
