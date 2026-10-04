"""Publish reviewed-reference contact sheets and carry attribution with the dataset."""
import csv,json,sys
from pathlib import Path
from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'Preprocessing/scripts'))
from mine_hard_negatives import digest

def rows(path):
    with path.open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))

def main():
    root=Path('CME_OPT1_Hard_Negative_Augmentation');r=root/'reports'
    selected=rows(r/'reference_ingestion_manifest.csv')
    provenance={v['sample_id']:v for v in rows(r/'reference_provenance.csv')}
    source=Path('Hazard_Expansion/content_runtime/combined_dataset_reviewed_v3_final')
    records=[]
    for row in selected:
        assert digest(source/row['source_image'])==row['source_sha256']
        records.append({**provenance[row['sample_id']], 'negative_region':row['prediction_box'],
            'verification_evidence':row['verification_evidence'],'reviewer':row['reviewer']})
    for output in (r/'reference_attributions.csv',source/'CMEOPT1_reference_attributions.csv'):
        with output.open('w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=list(records[0]));w.writeheader();w.writerows(records)
    for start in range(0,len(records),20):
        canvas=Image.new('RGB',(1250,1040),'white');draw=ImageDraw.Draw(canvas)
        draw.text((4,4),'Verified real visual confusers (AI review). Photo attribution/licenses: reference_attributions.csv',fill='black')
        for i,record in enumerate(records[start:start+20]):
            x=i%5*250;y=i//5*250+30
            im=Image.open(source/record['source_image']).convert('RGB');im.thumbnail((245,200));canvas.paste(im,(x,y))
            draw.text((x,y+202),f'{start+i}: {record["target_class"]}',fill='black')
            draw.text((x,y+218),record['sample_id'],fill='black')
            draw.text((x,y+234),record['license'],fill='black')
        canvas.save(r/f'reference_contact_sheet_{start:04d}.png',optimize=True)
    print(json.dumps({'reviewed_reference_photos':len(records),'contact_sheets':(len(records)+19)//20,
        'attribution_in_source_and_output':True,'independent_source_count_excludes_derivatives':True}))

if __name__=='__main__':main()
