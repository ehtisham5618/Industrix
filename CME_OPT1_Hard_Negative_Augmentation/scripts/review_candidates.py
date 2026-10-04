"""Build visual review sheets without converting predictions into verified labels."""
import argparse
import csv
import json
from pathlib import Path
from PIL import Image, ImageDraw


def render(dataset, rows, output, start=0, count=20):
    canvas=Image.new('RGB',(1250,1000),'white');draw=ImageDraw.Draw(canvas)
    for i,row in enumerate(rows[start:start+count]):
        image=Image.open(dataset/row['source_image']).convert('RGB')
        original=image.size;image.thumbnail((240,200))
        x=(i%5)*250;y=(i//5)*250
        canvas.paste(image,(x,y))
        if row.get('prediction_box'):
            box=json.loads(row['prediction_box'])
            draw.rectangle((x+box[0]*image.width,y+box[1]*image.height,x+box[2]*image.width,y+box[3]*image.height),outline='red',width=2)
        draw.text((x,y+205),f'{start+i}: {row["target_class"]}',fill='black')
        draw.text((x,y+222),row['failure_type'][:30],fill='black')
        draw.text((x,y+238),row['sample_id'][:26],fill='black')
    output.parent.mkdir(parents=True,exist_ok=True);canvas.save(output)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dataset',type=Path,required=True);p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--failure-type',default='hard_negative_candidate')
    a=p.parse_args()
    with a.manifest.open(encoding='utf-8-sig',newline='') as f:
        rows=[r for r in csv.DictReader(f) if r['failure_type']==a.failure_type]
    a.output.mkdir(parents=True,exist_ok=True)
    for start in range(0,len(rows),20): render(a.dataset,rows,a.output/f'review_{start:04d}.png',start)
    with (a.output/'review_index.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=['review_index','sample_id','source_image']);w.writeheader()
        w.writerows({'review_index':i,'sample_id':r['sample_id'],'source_image':r['source_image']} for i,r in enumerate(rows))
    print(f'Rendered {len(rows)} review candidates; verification remains pending.')

if __name__=='__main__':main()
