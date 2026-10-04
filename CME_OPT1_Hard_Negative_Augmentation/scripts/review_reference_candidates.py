"""Render fixed-index source photographs for semantic review; never approve automatically."""
import argparse,hashlib,json
from pathlib import Path
from PIL import Image,ImageDraw
import yaml

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--start',type=int,default=0);p.add_argument('--stop',type=int,default=10000)
    a=p.parse_args();root=Path('CME_OPT1_Hard_Negative_Augmentation')
    entries=[]
    for f in ('external_candidates.yaml','external_candidates_extra.yaml'):
        entries+=yaml.safe_load((root/'configs'/f).read_text(encoding='utf-8'))
    entries=list({e['title']:e for e in entries}.values())
    out=root/'review_references';out.mkdir(exist_ok=True)
    for start in range(a.start,min(a.stop,len(entries)),20):
        canvas=Image.new('RGB',(1600,1200),'white');draw=ImageDraw.Draw(canvas)
        for offset,entry in enumerate(entries[start:start+20]):
            key=hashlib.sha256(entry['title'].encode()).hexdigest()[:20]
            path=root/'runtime/reference_candidates/images/train'/f'commons_{key}.jpg'
            x=offset%5*320;y=offset//5*300
            if path.exists():
                im=Image.open(path).convert('RGB');im.thumbnail((315,245));canvas.paste(im,(x,y))
            draw.text((x,y+245),f'{start+offset}: {entry["target_class"]}',fill='black')
            draw.text((x,y+261),entry['title'][:48],fill='black')
            draw.text((x,y+277),key,fill='black')
        canvas.save(out/f'review_{start:04d}.png')
    print(f'Reference sheets rendered; {len(entries)} fixed candidate indices; approval remains manual.')

if __name__=='__main__':main()
