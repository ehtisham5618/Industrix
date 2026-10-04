"""Measure detector responses on already reviewed references without inventing verification."""
import csv,json,sys
from pathlib import Path
import torch
import yaml
from ultralytics import YOLO
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'Preprocessing/scripts'))
from mine_hard_negatives import digest

def main():
    root=Path('CME_OPT1_Hard_Negative_Augmentation');r=root/'reports'
    source=Path('Hazard_Expansion/content_runtime/combined_dataset_reviewed_v3_final')
    with (r/'reference_ingestion_manifest.csv').open(encoding='utf-8') as f:rows=list(csv.DictReader(f))
    torch.set_num_threads(4);model=YOLO('Backend/best.pt');records=[]
    names=yaml.safe_load((source/'data.yaml').read_text())['names']
    if isinstance(names,dict):names=[names[i] for i in range(len(names))]
    assert [model.names[i] for i in range(len(model.names))]==names,'Model/dataset class mapping differs'
    for i,row in enumerate(rows):
        path=source/row['source_image'];assert digest(path)==row['source_sha256']
        assert row['verification_status']=='verified' and row['ground_truth_present'].lower()=='false'
        assert not (source/'labels/train'/f'{path.stem}.txt').read_text().strip(),'Expected reviewed all-class-negative reference'
        result=model.predict(str(path),conf=.15,imgsz=640,device='cpu',verbose=False)[0]
        predictions=[{'class_id':int(b.cls.item()),'class_name':model.names[int(b.cls.item())],
            'confidence':float(b.conf.item()),'box_xyxyn':b.xyxyn[0].tolist()} for b in result.boxes if int(b.cls.item()) in (7,10)]
        records.append({'sample_id':row['sample_id'],'source_sha256':row['source_sha256'],
            'target_class':row['target_class'],'target_predictions':json.dumps(predictions),
            'observed_target_error':any(p['class_name']==row['target_class'] for p in predictions)})
        if (i+1)%25==0:print(f'References measured {i+1}/{len(rows)}',flush=True)
    with (r/'reference_detector_responses.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(records[0]));w.writeheader();w.writerows(records)
    summary={'model':'Backend/best.pt','model_sha256':digest(Path('Backend/best.pt')),
        'imgsz':640,'confidence':.15,'device':'cpu','images_measured':len(records),
        'images_with_assigned_target_error':sum(x['observed_target_error'] for x in records),
        'chemical_images_with_assigned_target_error':sum(x['observed_target_error'] and x['target_class']=='chemical hazard' for x in records),
        'smoke_images_with_assigned_target_error':sum(x['observed_target_error'] and x['target_class']=='smoke' for x in records),
        'note':'Errors measured only after independent visual/source review established target absence. Sources without a prediction remain could-cause visual confusers, not observed errors.'}
    (r/'reference_detector_summary.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
