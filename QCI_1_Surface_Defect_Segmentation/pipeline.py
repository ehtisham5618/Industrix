"""One-sample processing, disk-backed manifests and explicit quality gates."""
from __future__ import annotations

import csv
import hashlib
import heapq
import json
import logging
import sqlite3
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from . import VERSION
from .config import local_path,read_mapping
from .contracts import ClassMapping,DatasetConfig,ImageRecord,Issue,Performance,ProcessingResult,SegmentationSample
from .discovery import Inventory,SamplePlan,generated_split
from .errors import ConfigurationError,InvalidSampleError
from .preprocessing import prepare,save_pair
from .reporting import sanity_grid,statistics
from .validation import decode_image,read_annotations,file_hash

LOGGER=logging.getLogger('qci1')


def scan_sample(plan: SamplePlan, config: DatasetConfig, mapping: ClassMapping) -> tuple[SegmentationSample, dict[int,int]]:
    """Validate and preprocess one sample, with at most one decoded pair live."""
    relative=plan.image_path.relative_to(config.dataset_root).as_posix()
    split=plan.split or generated_split(relative,config)
    sample=SegmentationSample(sample_id=f'{split}/{plan.key}',split=split,image=ImageRecord(path=relative),
        annotation_path=plan.annotation_path.relative_to(config.dataset_root).as_posix() if plan.annotation_path else None)
    pixels:dict[int,int]={}
    try:
        image,record=decode_image(plan.image_path,config);sample.image=record
        if plan.split is None:
            sample.split=generated_split(str(record.pixel_sha256),config);sample.sample_id=f'{sample.split}/{plan.key}'
        if plan.duplicate_id:raise InvalidSampleError(Issue(code='DUPLICATE_SAMPLE_ID',stage='discovery',message='Multiple image extensions share the same pairing identity'))
        if plan.ambiguous_annotation:raise InvalidSampleError(Issue(code='AMBIGUOUS_ANNOTATION',stage='discovery',message='Multiple annotations share the same pairing identity'))
        if plan.annotation_path is None:raise InvalidSampleError(Issue(code='MISSING_ANNOTATION',stage='annotation',message='No corresponding annotation'))
        parsed=read_annotations(plan.annotation_path,record.width,record.height,config,mapping)
        sample.annotation_sha256=file_hash(plan.annotation_path)
        sample.annotation_kind=parsed.kind;sample.annotations=parsed.annotations;sample.warnings=parsed.warnings;sample.empty_annotation=parsed.empty
        prepared=prepare(image,parsed.mask,config);tensor=prepared.tensor()
        if tensor.shape!=(3,config.target_height,config.target_width) or not np.isfinite(tensor).all():
            raise InvalidSampleError(Issue(code='INVALID_PREPROCESSING',stage='preprocessing',message='Invalid normalized RGB tensor'))
        sample.transform=prepared.transform;sample.source_valid=True;sample.segmentation_valid=parsed.mask is not None
        if parsed.mask is not None:
            values,counts=np.unique(parsed.mask,return_counts=True)
            pixels={int(value)-1:int(count) for value,count in zip(values,counts) if value}
        else:
            sample.issues.append(Issue(code='BOXES_NOT_SEGMENTATION',stage='segmentation',message='Source boxes do not supply defect boundaries; no mask was invented'))
    except InvalidSampleError as exc:sample.issues.append(exc.issue)
    except (OSError,ValueError) as exc:
        sample.issues.append(Issue(code='SAMPLE_READ_ERROR',stage='image',message=str(exc)[:500],error_type=type(exc).__name__))
    return sample,pixels


def add_issue(db: sqlite3.Connection, code: str) -> None:
    """Store counters on disk with no dataset-sized Python error list."""
    db.execute('INSERT INTO issues(code,n) VALUES(?,1) ON CONFLICT(code) DO UPDATE SET n=n+1',(code,))


def retain_candidate(heap: list[tuple[int,str]], sample: SegmentationSample, config: DatasetConfig) -> None:
    """Keep bounded seeded identities, preferring annotated defects to empties."""
    rank=int(hashlib.sha256(f'{config.seed}:{sample.sample_id}'.encode()).hexdigest(),16)
    if sample.empty_annotation:rank+=2**256
    item=(-rank,sample.image.path)
    if len(heap)<config.sanity_capacity:heapq.heappush(heap,item)
    elif item>heap[0]:heapq.heapreplace(heap,item)


def run(config: DatasetConfig, offline_verified: bool = False) -> ProcessingResult:
    """Write typed actual-data reports; only genuine nonleaking pairs are exported."""
    config=DatasetConfig.model_validate(config.model_dump())
    began=time.perf_counter();config.dataset_root=local_path(config.dataset_root);config.output_dir=local_path(config.output_dir)
    if not config.dataset_root.is_dir():raise ConfigurationError('Dataset root does not exist')
    if config.output_dir.is_relative_to(config.dataset_root):raise ConfigurationError('Output cannot overwrite source inputs')
    mapping,metadata=read_mapping(config)
    config.output_dir.mkdir(parents=True,exist_ok=True)
    # Refuse to erase an earlier database. Every scan has its own bounded disk index.
    run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'_'+str(time.time_ns())
    index=config.output_dir/f'index_{run_id}.sqlite'
    inventory:Inventory|None=None;elapsed_samples=0.;box_heap:list[tuple[int,str]]=[];seg_heap:list[tuple[int,str]]=[]
    try:
        inventory=Inventory(index,config,metadata);db=inventory.connection
        for plan in inventory.plans():
            started=time.perf_counter();sample,pixels=scan_sample(plan,config,mapping);elapsed_samples+=time.perf_counter()-started
            db.execute('INSERT INTO samples VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (sample.image.path,sample.sample_id,sample.split,int(sample.source_valid),int(sample.segmentation_valid),sample.annotation_kind,int(sample.empty_annotation),
                 sample.image.width,sample.image.height,sample.image.sha256,sample.image.pixel_sha256,sample.model_dump_json()))
            # Geometry counts describe valid source annotations. Segmentation pixel
            # totals are updated after quarantine, only for eligible genuine masks.
            if sample.source_valid:
                for cid,n in Counter(a.class_id for a in sample.annotations).items():
                    db.execute('INSERT INTO class_counts(id,samples,instances,pixels) VALUES(?,1,?,0) ON CONFLICT(id) DO UPDATE SET samples=samples+1,instances=instances+excluded.instances',(cid,n))
                if sample.annotation_kind=='box':retain_candidate(box_heap,sample,config)
            for issue in sample.issues:
                add_issue(db,issue.code)
                if issue.code!='BOXES_NOT_SEGMENTATION':
                    LOGGER.warning(json.dumps(dict(sample_id=sample.sample_id,image_path=sample.image.path,annotation_path=sample.annotation_path,**issue.model_dump())))
        db.commit()
        # Both original encoded hashes and decoded-RGB hashes are stored. The
        # decoded key additionally catches lossless re-encoding/metadata changes.
        with (config.output_dir/'leakage.jsonl').open('w',encoding='utf-8') as audit:
            for row in db.execute('''SELECT path,result FROM samples s WHERE pixel_sha IN
                (SELECT pixel_sha FROM samples WHERE pixel_sha IS NOT NULL GROUP BY pixel_sha HAVING COUNT(*)>1) ORDER BY path'''):
                sample=SegmentationSample.model_validate_json(row['result'])
                cross=db.execute('SELECT COUNT(DISTINCT split) FROM samples WHERE pixel_sha=?',(sample.image.pixel_sha256,)).fetchone()[0]>1
                code='CROSS_SPLIT_DUPLICATE' if cross else 'WITHIN_SPLIT_DUPLICATE'
                sample.segmentation_valid=False;sample.issues.append(Issue(code=code,stage='leakage',message='Quarantined from segmentation export; source splits/files remain unchanged'))
                db.execute('UPDATE samples SET seg_valid=0,result=? WHERE path=?',(sample.model_dump_json(),sample.image.path));add_issue(db,code)
                audit.write(json.dumps(dict(sample_id=sample.sample_id,image_path=sample.image.path,file_sha256=sample.image.sha256,pixel_sha256=sample.image.pixel_sha256,cross_split=cross))+'\n')
        db.commit()
        with (config.output_dir/'orphan_annotations.jsonl').open('w',encoding='utf-8') as audit:
            for path in inventory.orphans():audit.write(json.dumps(dict(annotation_path=path,reason='ANNOTATION_WITHOUT_IMAGE'))+'\n')
        # Export only after validating duplicates. One sample at a time, into a
        # distinct run directory; previous runtime pairs are never silently reused.
        for row in db.execute('SELECT path,result FROM samples WHERE seg_valid=1 ORDER BY sample_id,path'):
            sample=SegmentationSample.model_validate_json(row['result'])
            image,current=decode_image(config.dataset_root/sample.image.path,config)
            if current.sha256!=sample.image.sha256 or file_hash(config.dataset_root/str(sample.annotation_path))!=sample.annotation_sha256:
                sample.segmentation_valid=False;sample.source_valid=False
                sample.issues.append(Issue(code='SOURCE_CHANGED_DURING_SCAN',stage='preprocessing',message='Input bytes changed between validation and export'))
                for cid,n in Counter(a.class_id for a in sample.annotations).items():
                    db.execute('UPDATE class_counts SET samples=samples-1,instances=instances-? WHERE id=?',(n,cid))
                db.execute('UPDATE samples SET source_valid=0,seg_valid=0,result=? WHERE path=?',(sample.model_dump_json(),sample.image.path))
                add_issue(db,'SOURCE_CHANGED_DURING_SCAN')
                continue
            parsed=read_annotations(config.dataset_root/str(sample.annotation_path),image.shape[1],image.shape[0],config,mapping)
            values,counts=np.unique(parsed.mask,return_counts=True)
            for value,count in zip(values,counts):
                if value:db.execute('UPDATE class_counts SET pixels=pixels+? WHERE id=?',(int(count),int(value)-1))
            if config.write_processed:
                prepared=prepare(image,parsed.mask,config)
                stem=hashlib.sha256(sample.sample_id.encode()).hexdigest()
                out_image=Path('processed')/run_id/'images'/sample.split/(stem+'.png')
                out_mask=Path('processed')/run_id/'masks'/sample.split/(stem+'.png')
                save_pair(prepared,config.output_dir/out_image,config.output_dir/out_mask)
                sample.processed_image=out_image.as_posix();sample.processed_mask=out_mask.as_posix()
            retain_candidate(seg_heap,sample,config)
            db.execute('UPDATE samples SET result=? WHERE path=?',(sample.model_dump_json(),sample.image.path))
        db.commit()
        def selected(heap: list[tuple[int,str]]) -> list[SegmentationSample]:
            return [SegmentationSample.model_validate_json(db.execute('SELECT result FROM samples WHERE path=?',(path,)).fetchone()[0]) for _,path in sorted(heap,reverse=True)]
        source_sanity=seg_sanity=None
        if box_heap:
            source_sanity='source_annotation_sanity_grid.png';sanity_grid(config,mapping,selected(box_heap),config.output_dir/source_sanity,False)
        if seg_heap:
            seg_sanity='segmentation_sanity_grid.png';sanity_grid(config,mapping,selected(seg_heap),config.output_dir/seg_sanity,True)
        stats=statistics(db,mapping)
        status='SUCCESS'
        if not stats.valid_segmentation_samples:status='BLOCKED' if stats.boxes_only_samples else 'FAILED'
        elif stats.valid_segmentation_samples!=stats.total_samples or stats.orphan_annotations:status='PARTIAL'
        # Serialized records and CSV are streamed, never collected as a list.
        with (config.output_dir/'samples.jsonl').open('w',encoding='utf-8') as records,(config.output_dir/'samples.csv').open('w',encoding='utf-8',newline='') as stream:
            fields=['sample_id','image','annotation','split','width','height','source_valid','segmentation_valid','annotation_kind','classes','issues','warnings','sha256','pixel_sha256','annotation_sha256','processed_image','processed_mask']
            writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
            for row in db.execute('SELECT result FROM samples ORDER BY sample_id,path'):
                sample=SegmentationSample.model_validate_json(row[0]);records.write(sample.model_dump_json()+'\n')
                writer.writerow(dict(sample_id=sample.sample_id,image=sample.image.path,annotation=sample.annotation_path,split=sample.split,width=sample.image.width,height=sample.image.height,
                    source_valid=sample.source_valid,segmentation_valid=sample.segmentation_valid,annotation_kind=sample.annotation_kind,
                    classes=';'.join(str(c) for c in sorted({a.class_id for a in sample.annotations})),issues=';'.join(i.code for i in sample.issues),warnings=';'.join(sample.warnings),
                    sha256=sample.image.sha256,pixel_sha256=sample.image.pixel_sha256,annotation_sha256=sample.annotation_sha256,processed_image=sample.processed_image,processed_mask=sample.processed_mask))
        duration=time.perf_counter()-began
        actual_format='indexed_mask' if config.annotation_format=='indexed_mask' else 'yolo_detection' if stats.boxes_only_samples and not stats.valid_segmentation_samples else 'yolo_segmentation' if stats.valid_segmentation_samples and not stats.boxes_only_samples else 'mixed_or_invalid_yolo'
        result=ProcessingResult(version=VERSION,dataset_name=config.dataset_root.name,source_metadata_sha256=file_hash(config.dataset_root/config.metadata_file),status=status,dataset_root=str(config.dataset_root),annotation_format=actual_format,
            class_mapping=mapping,statistics=stats,performance=Performance(duration_seconds=duration,samples_per_second=stats.total_samples/max(duration,1e-9),mean_sample_ms=1000*elapsed_samples/stats.total_samples),
            manifest_path=str(config.output_dir/'dataset_manifest.json'),samples_path=str(config.output_dir/'samples.jsonl'),
            source_sanity_path=str(config.output_dir/source_sanity) if source_sanity else None,segmentation_sanity_path=str(config.output_dir/seg_sanity) if seg_sanity else None,
            generated_at=datetime.now(timezone.utc),seed=config.seed,split_policy='Preserved source splits' if inventory.preserve_splits else 'Seeded decoded-content hash; documented 80/10/10 fallback',
            sanity_capacity=config.sanity_capacity,offline_verified=offline_verified,
            limitations=['Source boxes are not segmentation ground truth; no synthetic masks are exported'] if stats.boxes_only_samples else [])
        (config.output_dir/'dataset_manifest.json').write_text(result.model_dump_json(indent=2)+'\n',encoding='utf-8')
        (config.output_dir/'qci1_summary.json').write_text(result.model_dump_json(indent=2)+'\n',encoding='utf-8')
        (config.output_dir/'dataset_statistics.json').write_text(stats.model_dump_json(indent=2)+'\n',encoding='utf-8')
        LOGGER.info(json.dumps(dict(stage='complete',status=result.status,samples=stats.total_samples,segmentation_valid=stats.valid_segmentation_samples)))
        return result
    finally:
        if inventory is not None:inventory.close()
