"""Find a genuine model prediction in existing local dataset images."""
import json
import random
import zipfile
import numpy as np
from pathlib import Path
import cv2
from Backend.offline_policy import configure_local_runtime
configure_local_runtime()
from ESE_CPU1_Quantization.common import ROOT,digest

def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--textile',action='store_true');args=parser.parse_args()
    prefix='textile' if args.textile else 'hazard';classes=set(range(7)) if args.textile else {7,8,10}
    from ESE_CPU3_Soak_Test.engine import OpenVINODetector
    out=ROOT/'IFE_UI3_Demo_Packaging/runtime';out.mkdir(parents=True,exist_ok=True)
    archive=ROOT/'CME_OPT2_Model_Fine_Tuning/runtime/dataset.zip'
    dataset=zipfile.ZipFile(archive)
    labels=[n for n in dataset.namelist() if '/labels/' in '/'+n and n.endswith('.txt')];random.Random(43).shuffle(labels)
    labels.sort(key=lambda n:'cmeopt1_' in n)
    detector=OpenVINODetector();evaluated=[]
    for label in labels:
        rows=[line.split() for line in dataset.read(label).decode().splitlines() if line.strip()]
        if not any(int(r[0]) in classes for r in rows):continue
        stem=label.replace('labels/','images/')[:-4]
        path=next((stem+e for e in ('.jpg','.png','.jpeg') if stem+e in dataset.NameToInfo),None)
        if not path:continue
        source_bytes=dataset.read(path)
        import hashlib
        image=cv2.imdecode(np.frombuffer(source_bytes,np.uint8),cv2.IMREAD_COLOR);detections,_=detector.predict_batch([image]);ds=detections[0]
        item=dict(archive=str(archive.relative_to(ROOT)),archive_member=path,source_sha256=hashlib.sha256(source_bytes).hexdigest(),detections=ds)
        evaluated.append(item)
        hazards=[d for d in ds if d['class_id'] in classes and d['confidence']>=.60]
        print(len(evaluated),Path(path).name,[(d['class_name'],round(d['confidence'],3)) for d in ds],flush=True)
        if hazards:
            cv2.imwrite(str(out/(prefix+'_fixture.png')),image)
            item.update(fixture_sha256=digest(out/(prefix+'_fixture.png')),shape=list(image.shape),
                provenance='Existing dataset image, shown as a repeated still-image demonstration clip. Real model predictions, no injected detections. Not held-out accuracy evidence.')
            (out/('textile_selection.json' if args.textile else 'fixture_selection.json')).write_text(json.dumps(item,indent=2),encoding='utf-8')
            break
        if len(evaluated)>=100:raise RuntimeError('No verified hazard in first 100 images')
    else:raise RuntimeError('No matching dataset asset')
    (out/(prefix+'_scan.json')).write_text(json.dumps(evaluated,indent=2),encoding='utf-8')

if __name__=='__main__':main()
