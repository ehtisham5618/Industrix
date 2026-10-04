"""Download licensed reference candidates. Downloads remain unverified until visual review.

Commons file metadata is resolved through Wikipedia's shared image repository API.
Only explicit CC BY, CC BY-SA, CC0 and public-domain licenses are accepted.
"""
import argparse, csv, hashlib, json, re, sys, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import cv2
import yaml
sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'Preprocessing/scripts'))
from mine_hard_negatives import FIELDS, digest, dhash, write_manifest

AGENT = 'Industirx-CMEOPT1/1.0 (https://github.com/devlogixtechnology/industirx; ehtisham.malik5618@gmail.com)'

def fetch(url):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': AGENT}), timeout=25) as response:
                return response.read()
        except Exception:
            if attempt == 2: raise
            time.sleep(attempt + 1)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--candidates',type=Path,default=Path('CME_OPT1_Hard_Negative_Augmentation/configs/external_candidates.yaml'))
    p.add_argument('--cache',type=Path,default=Path('CME_OPT1_Hard_Negative_Augmentation/runtime/reference_candidates'))
    p.add_argument('--reports',type=Path,default=Path('CME_OPT1_Hard_Negative_Augmentation/reports'))
    a=p.parse_args(); entries=yaml.safe_load(a.candidates.read_text(encoding='utf-8'))
    extra=a.candidates.with_name('external_candidates_extra.yaml')
    if extra.exists(): entries += yaml.safe_load(extra.read_text(encoding='utf-8'))
    entries=list({e['title']:e for e in entries}.values())
    images=a.cache/'images/train'; images.mkdir(parents=True,exist_ok=True)
    metadata_path=a.cache/'commons_metadata.json'
    metadata=json.loads(metadata_path.read_text(encoding='utf-8')) if metadata_path.exists() else {}
    missing=[e for e in entries if e['title'] not in metadata]
    for offset in range(0,len(missing),25):
        titles=[e['title'] for e in missing[offset:offset+25]]
        params={'action':'query','titles':'|'.join(titles),'prop':'imageinfo','iiprop':'url|extmetadata','iiurlwidth':640,'format':'json'}
        data=json.loads(fetch('https://en.wikipedia.org/w/api.php?'+urllib.parse.urlencode(params)))
        aliases={r['to']:r['from'] for r in data['query'].get('normalized',[])}
        for page in data['query']['pages'].values():
            title=aliases.get(page['title'],page['title'])
            metadata[title]=page.get('imageinfo',[{}])[0]
        metadata_path.write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
        print(f'Metadata {min(offset+25,len(missing))}/{len(missing)}',flush=True)
    def download(entry):
        info=metadata.get(entry['title'],{}); ext=info.get('extmetadata',{})
        val=lambda key: ext.get(key,{}).get('value','')
        license=val('LicenseShortName')
        if not (license.startswith(('CC BY ','CC BY-SA ')) or license in ('CC0','Public domain')):
            return None, {'title':entry['title'],'reason':f'Unapproved/missing license: {license}'}
        try:
            url=info.get('thumburl',info['url']).split('?')[0]
            key=hashlib.sha256(entry['title'].encode()).hexdigest()[:20]
            path=images/f'commons_{key}.jpg'
            if not path.exists(): path.write_bytes(fetch(url))
            image=cv2.imread(str(path))
            if image is None: raise ValueError('Image cannot be decoded')
            provenance={'sample_id':key,'title':entry['title'],'target_class':entry['target_class'],
                'source_image':path.relative_to(a.cache).as_posix(),'source_sha256':digest(path),
                'description_url':info['descriptionurl'],'download_url':url,'license':license,
                'license_url':val('LicenseUrl'),'artist_html':val('Artist'),'credit_html':val('Credit'),
                'description_html':val('ImageDescription'),'categories':val('Categories'),
                'date_original':val('DateTimeOriginal'),'modification':'Commons resized thumbnail; no crop or other edit',
                'perceptual_hash':f'{dhash(image):016x}','flipped_perceptual_hash':f'{dhash(cv2.flip(image,1)):016x}'}
            return provenance,None
        except Exception as exc: return None,{'title':entry['title'],'reason':str(exc)}
    records=[];errors=[]
    with ThreadPoolExecutor(max_workers=2) as pool:
        for index,(record,error) in enumerate(pool.map(download,entries)):
            if record: records.append(record)
            if error: errors.append(error)
            if (index+1)%25==0:print(f'Downloads {index+1}/{len(entries)}; usable={len(records)}',flush=True)
    a.reports.mkdir(parents=True,exist_ok=True)
    if records:
        with (a.reports/'reference_provenance.csv').open('w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=list(records[0]));w.writeheader();w.writerows(records)
    rows=[]
    for record in records:
        row={k:'' for k in FIELDS}; row.update(sample_id=record['sample_id'],source_image=record['source_image'],
            source_sha256=record['source_sha256'],split='train',target_class=record['target_class'],
            failure_type='potential_hard_negative',ground_truth_present='unknown',prediction_box='[0,0,1,1]',
            reason='Licensed reference candidate; hazard absence and visual confusion require review',
            selected_for_augmentation='false',augmentation_strategy='color_jitter,hsv,mosaic'+(',chemical_sheen' if record['target_class']=='chemical hazard' else ''),
            verification_status='pending',perceptual_hash=record['perceptual_hash'])
        rows.append(row)
    write_manifest(a.reports/'reference_candidates.csv',rows)
    (a.reports/'reference_download_failures.json').write_text(json.dumps(errors,indent=2),encoding='utf-8')
    print(json.dumps({'downloaded':len(records),'excluded_or_failed':len(errors),'verified':0}))

if __name__=='__main__':main()
