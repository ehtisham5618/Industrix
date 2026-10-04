"""Generate comparison figures, QC evidence and manifest-derived completion status."""
import argparse,csv,json,sys,re
from collections import Counter
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'Preprocessing/scripts'))
from mine_hard_negatives import digest,read_labels
from augment_hard_negatives import qualifying,snapshot,safe_source


def read_csv(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reports',type=Path,default=Path('CME_OPT1_Hard_Negative_Augmentation/reports'))
    p.add_argument('--source',type=Path,default=Path('Hazard_Expansion/content_runtime/combined_dataset'))
    p.add_argument('--dataset',type=Path,default=Path('Hazard_Expansion/content_runtime/combined_dataset_augmented'))
    p.add_argument('--selection',type=Path)
    p.add_argument('--original',type=Path,default=Path('Hazard_Expansion/content_runtime/combined_dataset'))
    a=p.parse_args();r=a.reports
    before=json.loads((r/'before/statistics.json').read_text());after=json.loads((r/'after/statistics.json').read_text())
    summary=json.loads((r/'augmentation_summary.json').read_text()); additions=read_csv(r/'augmentation_manifest.csv')
    selection=read_csv(a.selection or r/'reviewed_selection.csv');q=qualifying(selection)
    manifest_sources={sha for row in additions for sha in json.loads(row['source_sha256'])}
    q={sha:row for sha,row in q.items() if sha in manifest_sources}
    counts=Counter(row['augmentation_type'] for row in additions)
    table=[]
    for i,name in enumerate(before['class_names']):
        b=before['splits']['train']['class_counts'].get(str(i),0);f=after['splits']['train']['class_counts'].get(str(i),0)
        table.append([i,name,b,f-b,f,before['splits']['val']['class_counts'].get(str(i),0),before['splits']['test']['class_counts'].get(str(i),0)])
    with (r/'class_balance_before_after.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f);w.writerow(['class_id','class','train_before','added','train_after','val','test']);w.writerows(table)
    x=range(len(table));fig,ax=plt.subplots(figsize=(13,6));
    ax.bar([v-.2 for v in x],[t[2] for t in table],width=.4,label='Before')
    ax.bar([v+.2 for v in x],[t[4] for t in table],width=.4,label='After')
    ax.set_xticks(list(x),[t[1] for t in table],rotation=35,ha='right');ax.set_ylabel('Training annotations')
    ax.set_title('CME-OPT1: training class representation (evaluation splits unchanged)');ax.legend();fig.tight_layout()
    fig.savefig(r/'class_balance_before_after.png',dpi=140);plt.close(fig)
    eval_same=snapshot(a.source)==snapshot(a.dataset)
    used=[row for row in selection if row['source_sha256'] in manifest_sources]
    for row in used:safe_source(a.source.resolve(),row)
    assert all(row['split']=='train' and row['output_image'].startswith('images/train/') for row in additions)
    assert all(digest(a.dataset/row['output_image'])==row['output_sha256'] for row in additions)
    source_snapshot=snapshot(a.source,('train','val','test'))
    source_preserved=all(digest(a.dataset/path)==sha for path,sha in source_snapshot.items())
    original_snapshot=snapshot(a.original,('train','val','test'))
    original_preserved=all(digest(a.dataset/path)==sha for path,sha in original_snapshot.items())
    original_families={split:{re.sub(r'_aug\d+$','',p.stem).split('.rf.')[0] for p in (a.source/'images'/split).glob('*')} for split in ('train','val','test')}
    leakage={f'{s1}-{s2}':len(original_families[s1]&original_families[s2]) for s1,s2 in [('train','val'),('train','test'),('val','test')]}
    photo_same=True
    source_by_path={row['source_image']:row for row in selection}
    for row in additions:
        if row['augmentation_type']!='mosaic':
            original=json.loads(row['source_image'])[0];stem=Path(original).stem
            photo_same &= (a.source/'labels/train'/f'{stem}.txt').read_bytes()==(a.dataset/'labels/train'/f'{Path(row["output_image"]).stem}.txt').read_bytes()
    assert eval_same and source_preserved and original_preserved and photo_same
    evaluation_families=original_families['val'] | original_families['test']
    selected_no_eval_overlap=all(re.sub(r'_aug\d+$','',Path(row['source_image']).stem).split('.rf.')[0] not in evaluation_families for row in used)
    assert selected_no_eval_overlap, 'An augmented source family overlaps evaluation'
    audit={'evaluation_bytes_unchanged':eval_same,'all_original_image_label_bytes_retained':source_preserved,
           'original_combined_dataset_bytes_retained':original_preserved,
           'photometric_label_bytes_unchanged':photo_same,'all_sources_train_and_hash_verified':True,
           'all_output_hashes_verified':True,'no_augmented_source_evaluation_family_overlap':selected_no_eval_overlap,'known_original_filename_family_cross_split_overlap':leakage,
           'note':'Filename families cover known _aug and Roboflow derivatives, not unknown renamed derivatives.'}
    (r/'lineage_audit.json').write_text(json.dumps(audit,indent=2))
    # QC panel: sources and each required transform; existing YOLO classes retain their actual IDs.
    panels=[]
    for typ in ('potential_hard_negative','hard_negative_candidate'):
        row=next(row for row in used if row['failure_type']==typ)
        panels.append((a.source/row['source_image'],a.source/'labels/train'/f'{Path(row["source_image"]).stem}.txt',f'{typ}: {row["target_class"]}'))
    for strategy in ('color_jitter','hsv','chemical_sheen','mosaic','smoke_overlay'):
        row=next(row for row in additions if row['augmentation_type']==strategy)
        panels.append((a.dataset/row['output_image'],a.dataset/'labels/train'/f'{Path(row["output_image"]).stem}.txt',f'{strategy}: {row["target_category"]}'))
    positive=next(row for row in additions if row['source_failure_type']=='hard_positive' and row['target_category']=='chemical hazard')
    panels.append((a.dataset/positive['output_image'],a.dataset/'labels/train'/f'{Path(positive["output_image"]).stem}.txt','chemical annotation-supported positive'))
    canvas=Image.new('RGB',(1200,680),'white');draw=ImageDraw.Draw(canvas)
    for i,(image_path,label_path,title) in enumerate(panels):
        im=Image.open(image_path).convert('RGB');im.thumbnail((290,295));x=i%4*300;y=i//4*340;canvas.paste(im,(x,y))
        for cls,xc,yc,bw,bh in read_labels(label_path):
            box=(x+(xc-bw/2)*im.width,y+(yc-bh/2)*im.height,x+(xc+bw/2)*im.width,y+(yc+bh/2)*im.height)
            draw.rectangle(box,outline='cyan',width=2);draw.text((box[0],box[1]),str(int(cls)),fill='red')
        draw.text((x+2,y+300),title[:45],fill='black');draw.text((x+2,y+316),image_path.stem[:40],fill='black')
    canvas.save(r/'qc_contact_sheet.png')
    validation=json.loads((r/'after/validation.json').read_text())
    representation=all(after['splits'][split]['class_counts'].get(str(i),0)>0 for split in ('train','val','test') for i in range(12))
    assert representation,'All 12 classes must remain represented in every split'
    qualifying_counts=Counter(row['target_class'] for row in q.values())
    observed={sha for sha,row in q.items() if row['failure_type']=='hard_negative_candidate'}
    responses=r/'reference_detector_responses.csv'
    if responses.exists():
        observed.update(row['source_sha256'] for row in read_csv(responses)
            if row['source_sha256'] in q and row['observed_target_error'].lower()=='true'
            and row['target_class']==q[row['source_sha256']]['target_class'])
    breakdown={}
    for target in ('chemical hazard','smoke'):
        subset=[row for row in used if row['target_class']==target]
        added=[row for row in additions if row['target_category']==target]
        breakdown[target]={'observed_verified_hard_negative_images':sum(row['failure_type']=='hard_negative_candidate' for row in subset),
            'observed_after_640_reference_check':sum(q[sha]['target_class']==target for sha in observed),
            'potential_confuser_images':sum(row['failure_type']=='potential_hard_negative' for row in subset),
            'hard_positive_images':sum(row['failure_type']=='hard_positive' for row in subset),
            'augmented_real_images':sum(row['sample_type']=='augmented_real' for row in added),
            'mosaics':sum(row['sample_type']=='mosaic' for row in added),
            'synthetic_overlays':sum(row['sample_type']=='synthetic_overlay' for row in added)}
    result={'source_version':summary['source_version'],'output_version':summary['version'],'seed':summary['seed'],
        'source_dataset':str(a.source),'output_dataset':str(a.dataset),'before_images':{s:d['image_count'] for s,d in before['splits'].items()},
        'after_images':{s:d['image_count'] for s,d in after['splits'].items()},'augmentation_counts':dict(counts),'target_breakdown':breakdown,
        'chemical_qualifying_examples':qualifying_counts['chemical hazard'],'smoke_qualifying_examples':qualifying_counts['smoke'],
        'combined_qualifying_examples':len(q),'requirement_150':'PASS' if len(q)>=150 else 'FAIL',
        'count_definition':summary['count_definition'],'dataset_validation':'PASS' if validation['passed'] else 'FAIL',
        'all_12_classes_represented_in_each_split':representation,
        'overall':'PASS' if validation['passed'] and len(q)>=150 else 'FAIL',
        'hard_negative_images':len(q),'hard_negative_regions':len(q),
        'hard_positive_images':sum(row['failure_type']=='hard_positive' for row in used),
        'hard_positive_annotations':sum(sum(int(b[0]) in (7,10) for b in read_labels(a.source/'labels/train'/f'{Path(row["source_image"]).stem}.txt')) for row in used if row['failure_type']=='hard_positive'),
        'augmented_positive_annotations':sum(int(row['target_annotations']) for row in additions),
        'observed_negative_images':len(observed),
        'verified_visual_confuser_images':len(q)-len(observed),
        'new_real_reference_images':len(read_csv(r/'reference_ingestion_manifest.csv')) if (r/'reference_ingestion_manifest.csv').exists() else 0,
        'limitations':['Observed detector errors and verified could-cause visual confusers are reported separately; count follows task section 13, and excludes positives/derivatives.',
            'Initial mining used 320 pixels; additional full-source 640-pixel mining and reference measurements screen failures, not deployment accuracy.',
            'Some unmatched smoke predictions overlap visible unlabelled smoke; excluded from negative selection.',
            'Licensed outdoor references are supplemental negatives; domain transfer to textile factories is unproven.',
            'Verification was performed by Codex visual review, not by a human peer reviewer.',
            'No proof of model accuracy improvement without follow-up retraining/evaluation.']}
    (r/'completion_status.json').write_text(json.dumps(result,indent=2))
    md=['# CME-OPT1 execution results','',f'Overall: **{result["overall"]}**. Dataset-format validation: **{result["dataset_validation"]}** (documented inherited lineage overlap remains).',
        f'Qualifying verified negatives: chemical {qualifying_counts["chemical hazard"]}, smoke {qualifying_counts["smoke"]}, combined {len(q)}. >=150: **{result["requirement_150"]}**.',
        '',result['count_definition'],'',f'Observed errors: {result["observed_negative_images"]}; verified visual confusers: {result["verified_visual_confuser_images"]}; new real reference photos: {result["new_real_reference_images"]}.',
        '', '| ID | Class | Train before | Added | Train after | Val | Test |','|---|---|---:|---:|---:|---:|---:|']
    md+=['| '+' | '.join(map(str,t))+' |' for t in table]
    md+=['','## Target breakdown','', '```json',json.dumps(breakdown,indent=2),'```','',
         '## Transforms','',json.dumps(dict(counts)),'','## Integrity','', '```json',json.dumps(audit,indent=2),'```','',
         f'Corrupt: {validation["corrupted_images"]}; invalid labels: {validation["invalid_labels"]}; missing labels: {validation["missing_labels"]}; orphan labels: {validation["missing_images"]}; exact cross-split duplicates: {validation["cross_split_duplicates"]}.',
         '',f'Existing rounded-edge boxes accepted within documented 0.0001 normalized tolerance: {validation["rounded_edge_boxes"]}.',
         '', '## Follow-up','', 'Obtain peer review and evaluate domain transfer after retraining. Rebuild inherited splits by source family and audit incomplete hazard labels before claiming accuracy gains. The dataset optimization deliverable does not certify detector improvement.',
         '', '## Limitations','']+[f'- {note}' for note in result['limitations']]
    (r/'RESULTS.md').write_text('\n'.join(md)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))

if __name__=='__main__': main()
