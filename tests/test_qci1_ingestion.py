"""Tiny labelled fixtures validate QCI logic; none are production data claims."""
from __future__ import annotations

import json
import socket
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
import yaml
from PIL import Image
from pydantic import ValidationError

from QCI_1_Surface_Defect_Segmentation.config import ROOT,load_config,read_mapping
from QCI_1_Surface_Defect_Segmentation.contracts import ClassMapping,DatasetConfig,ImageRecord,SegmentationAnnotation,SegmentationSample
from QCI_1_Surface_Defect_Segmentation.discovery import Inventory,generated_split
from QCI_1_Surface_Defect_Segmentation.errors import ConfigurationError,InvalidSampleError
from QCI_1_Surface_Defect_Segmentation.offline import no_network
from QCI_1_Surface_Defect_Segmentation.pipeline import run,scan_sample
from QCI_1_Surface_Defect_Segmentation.preprocessing import prepare
from QCI_1_Surface_Defect_Segmentation.validation import decode_image,read_annotations


@pytest.fixture
def tmp_path():
    base=ROOT/'QCI_1_Surface_Defect_Segmentation/runtime';base.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='pytest_',dir=base) as path:yield Path(path)


def dataset(tmp: Path, mask: bool=False, split: bool=True) -> DatasetConfig:
    root=tmp/'source';root.mkdir()
    metadata={'nc':2,'names':['tear','stain']}
    for name in ('train','val','test') if split else ('',):
        (root/'images'/name).mkdir(parents=True)
        (root/('masks' if mask else 'labels')/name).mkdir(parents=True)
        if split:metadata[name]='images/'+name
    (root/'data.yaml').write_text(yaml.safe_dump(metadata),encoding='utf-8')
    return DatasetConfig(dataset_root=root,output_dir=tmp/'output',target_width=32,target_height=32,
        annotation_format='indexed_mask' if mask else 'yolo',annotation_dir='masks' if mask else 'labels',
        annotation_extension='.png' if mask else '.txt',empty_yolo_annotation_kind='polygon')


def image(config: DatasetConfig, name: str='a', split: str='train', color: int=80, size: tuple[int,int]=(32,32)) -> Path:
    path=config.dataset_root/'images'/split/(name+'.png')
    pixels=np.full((size[1],size[0],3),color,dtype=np.uint8);pixels[0,0]=[1,2,3]
    Image.fromarray(pixels).save(path);return path


def label(config: DatasetConfig, text: str='0 .25 .25 .75 .25 .75 .75 .25 .75', name: str='a', split: str='train') -> Path:
    path=config.dataset_root/'labels'/split/(name+'.txt');path.write_text(text,encoding='utf-8');return path


def test_real_polygon_to_indexed_mask_and_normalized_pair(tmp_path):
    cfg=dataset(tmp_path);image(cfg);path=label(cfg);mapping,_=read_mapping(cfg)
    result=read_annotations(path,32,32,cfg,mapping)
    assert result.kind=='polygon' and set(np.unique(result.mask))=={0,1}
    assert np.count_nonzero(result.mask==1)==17*17
    rgb,_=decode_image(cfg.dataset_root/'images/train/a.png',cfg);prepared=prepare(rgb,result.mask,cfg)
    tensor=prepared.tensor();assert tensor.dtype==np.float32 and tensor.flags.c_contiguous
    assert tensor.shape==(3,32,32) and 0<=tensor.min()<=tensor.max()<=1


def test_full_pipeline_manifest_counts_and_export(tmp_path):
    cfg=dataset(tmp_path);image(cfg);label(cfg)
    result=run(cfg)
    assert result.status=='SUCCESS' and result.statistics.valid_segmentation_samples==1
    rows=[json.loads(l) for l in Path(result.samples_path).read_text().splitlines()]
    row=rows[0];assert (cfg.output_dir/row['processed_mask']).exists()
    assert (cfg.output_dir/row['processed_image']).exists()
    assert result.segmentation_sanity_path and Path(result.segmentation_sanity_path).exists()
    assert result.statistics.classes[0].foreground_pixels==289


def test_actual_boxes_are_not_promoted_to_segmentation(tmp_path):
    cfg=dataset(tmp_path);image(cfg);label(cfg,'0.0 .5 .5 .5 .5')
    result=run(cfg);assert result.status=='BLOCKED'
    assert result.statistics.source_valid_samples==1 and result.statistics.valid_segmentation_samples==0
    assert result.statistics.classes[0].foreground_pixels is None
    assert result.segmentation_sanity_path is None and not (cfg.output_dir/'processed').exists()
    row=json.loads(Path(result.samples_path).read_text().splitlines()[0]);assert row['annotations'][0]['kind']=='box'
    assert 'INTEGER_CLASS_TOKEN_NORMALIZED' in row['warnings'] and row['processed_mask'] is None


def test_empty_detection_label_does_not_invent_background_mask(tmp_path):
    cfg=dataset(tmp_path);cfg.empty_yolo_annotation_kind='box';image(cfg);label(cfg,'')
    result=run(cfg);assert result.status=='BLOCKED'
    assert result.statistics.empty_annotations==1 and result.statistics.valid_segmentation_samples==0


def test_explicit_polygon_negative_is_preserved(tmp_path):
    cfg=dataset(tmp_path);image(cfg);label(cfg,'')
    result=run(cfg);assert result.status=='SUCCESS' and result.statistics.empty_annotations==1
    sample=json.loads(Path(result.samples_path).read_text().splitlines()[0])
    assert np.unique(np.array(Image.open(cfg.output_dir/sample['processed_mask']))).tolist()==[0]


@pytest.mark.parametrize('text,code',[
    ('7 .5 .5 .2 .2','INVALID_CLASS_ID'),('0.5 .5 .5 .2 .2','INVALID_CLASS_ID'),('nan .5 .5 .2 .2','INVALID_CLASS_ID'),
    ('0.000000000000000001 .5 .5 .2 .2','INVALID_CLASS_ID'),('1e999999999 .5 .5 .2 .2','INVALID_CLASS_ID'),
    ('0 .5 .5 nan .2','MALFORMED_BOX'),('0 .5 .5 -1 .2','MALFORMED_BOX'),('0 .99 .5 .5 .5','MALFORMED_BOX'),
    ('0 0 0 .5 .5 .9','MALFORMED_ANNOTATION'),('0 0 0 1 0 1 1 0','MALFORMED_ANNOTATION'),
    ('0 0 0 .5 .5 1 1','ZERO_AREA_POLYGON'),('0 0 0 1 1 0 1 1 0','SELF_INTERSECTING_POLYGON'),
    ('0 0 0 1.1 0 1 1','POLYGON_BOUNDS'),('0 0 0 inf 0 1 1','POLYGON_BOUNDS'),
    ('0 0 0 1 0 1 1 1 0','MALFORMED_POLYGON'),('0 .5 .5 .4 .4\n1 .1 .1 .9 .1 .9 .9 .1 .9','MIXED_ANNOTATION_FORMAT')])
def test_invalid_annotation_is_structured(tmp_path,text,code):
    cfg=dataset(tmp_path);path=label(cfg,text);mapping,_=read_mapping(cfg)
    with pytest.raises(InvalidSampleError) as found:read_annotations(path,32,32,cfg,mapping)
    assert found.value.issue.code==code


def test_polygon_closing_vertex_is_normalized(tmp_path):
    cfg=dataset(tmp_path);path=label(cfg,'0 .1 .1 .9 .1 .9 .9 .1 .9 .1 .1');mapping,_=read_mapping(cfg)
    assert len(read_annotations(path,32,32,cfg,mapping).annotations[0].polygon)==4


def test_different_class_overlap_is_rejected(tmp_path):
    cfg=dataset(tmp_path);path=label(cfg,'0 .1 .1 .9 .1 .9 .9 .1 .9\n1 .2 .2 .8 .2 .8 .8 .2 .8');mapping,_=read_mapping(cfg)
    with pytest.raises(InvalidSampleError,match='overlap'):read_annotations(path,32,32,cfg,mapping)


def test_same_class_overlap_unions_pixels(tmp_path):
    cfg=dataset(tmp_path);path=label(cfg,'0 .25 .25 .75 .25 .75 .75 .25 .75\n0 .25 .25 .75 .25 .75 .75 .25 .75');mapping,_=read_mapping(cfg)
    result=read_annotations(path,32,32,cfg,mapping);assert np.count_nonzero(result.mask)==289 and len(result.annotations)==2


def test_missing_pair_and_orphan_are_reported(tmp_path):
    cfg=dataset(tmp_path);image(cfg);label(cfg,name='orphan')
    result=run(cfg);assert result.statistics.invalid_source_samples==1 and result.statistics.orphan_annotations==1
    assert result.statistics.issues['MISSING_ANNOTATION']==1
    assert 'orphan.txt' in (cfg.output_dir/'orphan_annotations.jsonl').read_text()


def test_corrupted_image_does_not_abort_other_samples(tmp_path):
    cfg=dataset(tmp_path);image(cfg);label(cfg);bad=image(cfg,'broken',color=30);bad.write_bytes(b'corrupted JPEG')
    label(cfg,name='broken');result=run(cfg)
    assert result.status=='PARTIAL' and result.statistics.source_valid_samples==1
    assert result.statistics.issues['CORRUPTED_IMAGE']==1


@pytest.mark.parametrize('case,code', [('bad','CORRUPTED_MASK'),('size','DIMENSION_MISMATCH'),('class','INVALID_MASK_CLASS'),('rgb','MASK_NOT_INDEXED')])
def test_invalid_masks(tmp_path,case,code):
    cfg=dataset(tmp_path,mask=True);image(cfg);path=cfg.dataset_root/'masks/train/a.png'
    if case=='bad':path.write_bytes(b'not a mask')
    elif case=='size':Image.fromarray(np.zeros((8,8),np.uint8)).save(path)
    elif case=='class':Image.fromarray(np.full((32,32),255,np.uint8)).save(path)
    else:Image.fromarray(np.zeros((32,32,3),np.uint8)).save(path)
    result=run(cfg);assert result.statistics.issues[code]==1 and not result.statistics.valid_segmentation_samples


def test_indexed_mask_validates_pixels_and_preserves_labels(tmp_path):
    cfg=dataset(tmp_path,mask=True);image(cfg);mask=np.zeros((32,32),np.uint8);mask[4:10,4:10]=2
    Image.fromarray(mask).save(cfg.dataset_root/'masks/train/a.png')
    result=run(cfg);assert result.status=='SUCCESS' and result.statistics.classes[1].foreground_pixels==36


def test_mask_letterbox_uses_nearest_not_intermediate_classes(tmp_path):
    cfg=dataset(tmp_path);cfg.target_width=6;cfg.target_height=6
    mask=np.tile([1,2,1,2,1,2,1,2],(4,1)).astype(np.uint8);rgb=np.zeros((4,8,3),np.uint8)
    output=prepare(rgb,mask,cfg)
    assert set(np.unique(output.mask))=={0,1,2} and output.transform.resized_height==3
    assert np.all(output.mask[:output.transform.pad_top]==0)


def test_cross_split_reencoded_image_is_quarantined(tmp_path):
    cfg=dataset(tmp_path);source=image(cfg);label(cfg);image(cfg,'same','val');label(cfg,name='same',split='val')
    # Changed PNG encoding bytes still retain the same decoded-RGB hash.
    Image.open(source).save(cfg.dataset_root/'images/val/same.png',compress_level=1)
    result=run(cfg);assert result.statistics.cross_split_hash_groups==1
    assert result.statistics.valid_segmentation_samples==0 and result.segmentation_sanity_path is None
    assert result.statistics.issues['CROSS_SPLIT_DUPLICATE']==2


def test_within_split_duplicate_images_are_quarantined(tmp_path):
    cfg=dataset(tmp_path);image(cfg);image(cfg,'b');label(cfg);label(cfg,name='b')
    result=run(cfg);assert result.statistics.duplicate_hash_groups==1
    assert result.statistics.issues['WITHIN_SPLIT_DUPLICATE']==2


def test_duplicate_pairing_identity_is_rejected(tmp_path):
    cfg=dataset(tmp_path);p=image(cfg);Image.open(p).save(p.with_suffix('.jpg'));label(cfg)
    result=run(cfg);assert result.statistics.duplicate_sample_ids==1
    assert result.statistics.issues['DUPLICATE_SAMPLE_ID']==2


def test_existing_splits_and_seed_are_preserved(tmp_path):
    cfg=dataset(tmp_path);image(cfg,'a','train',color=30);image(cfg,'b','test',color=100);label(cfg);label(cfg,name='b',split='test')
    result=run(cfg);assert result.statistics.split_counts=={'train':1,'val':0,'test':1}
    assert result.split_policy=='Preserved source splits'


def test_unsplit_assignment_is_reproducible_and_grouped_by_content(tmp_path):
    cfg=dataset(tmp_path,split=False);image(cfg,split='');label(cfg,split='')
    one=run(cfg);two=run(cfg);assert one.statistics.split_counts==two.statistics.split_counts
    assert generated_split('identical',cfg)==generated_split('identical',cfg)
    assert 'Seeded decoded-content hash' in one.split_policy


def test_offline_pipeline_attempts_zero_connections(tmp_path):
    cfg=dataset(tmp_path);image(cfg);label(cfg)
    with no_network() as audit:result=run(cfg,offline_verified=True)
    assert audit.attempts==0 and result.offline_verified
    with no_network() as audit:
        with socket.socket() as sock:
            with pytest.raises(OSError,match='forbids'):sock.connect(('203.0.113.1',443))
    assert audit.attempts==1


def test_pixel_and_byte_caps_reject_before_large_allocation(tmp_path):
    cfg=dataset(tmp_path);path=image(cfg);cfg.target_width=16;cfg.target_height=16;cfg.max_pixels=500
    with pytest.raises(InvalidSampleError) as found:decode_image(path,cfg)
    assert found.value.issue.code=='IMAGE_PIXEL_LIMIT'
    cfg.max_pixels=4096;cfg.max_image_bytes=1
    with pytest.raises(InvalidSampleError) as found:decode_image(path,cfg)
    assert found.value.issue.code=='IMAGE_BYTE_LIMIT'


def test_annotation_size_and_instance_caps(tmp_path):
    cfg=dataset(tmp_path);mapping,_=read_mapping(cfg);path=label(cfg);cfg.max_annotation_bytes=1
    with pytest.raises(InvalidSampleError,match='byte'):read_annotations(path,32,32,cfg,mapping)
    cfg.max_annotation_bytes=1000;cfg.max_instances=1;path=label(cfg,'0 .5 .5 .2 .2\n0 .5 .5 .1 .1')
    with pytest.raises(InvalidSampleError,match='instances'):read_annotations(path,32,32,cfg,mapping)


def test_permission_error_is_a_structured_sample_failure(tmp_path):
    cfg=dataset(tmp_path);image(cfg);label(cfg);mapping,metadata=read_mapping(cfg)
    inventory=Inventory(tmp_path/'test.sqlite',cfg,metadata)
    try:
        plan=next(inventory.plans())
        with patch('QCI_1_Surface_Defect_Segmentation.validation.Image.open',side_effect=PermissionError('Denied')):
            sample,_=scan_sample(plan,cfg,mapping)
        assert sample.issues[0].code=='IMAGE_READ_ERROR' and not sample.source_valid
    finally:inventory.close()


@pytest.mark.parametrize('change', [dict(dataset_root=''),dict(target_width=-1),dict(target_height=True),dict(sanity_capacity=13),dict(split_ratios=(.8,.8,.2)),dict(annotation_format='coco'),dict(image_dir='../escape')])
def test_malformed_config_contracts_are_rejected(tmp_path,change):
    values=dict(dataset_root=tmp_path,output_dir=tmp_path/'out');values.update(change)
    with pytest.raises(ValidationError):DatasetConfig(**values)


@pytest.mark.parametrize('names', [{2:'tear'},{0:''},{0:'tear',1:'tear'},{True:'tear'}])
def test_malformed_mapping_is_rejected(names):
    with pytest.raises(ValidationError):ClassMapping(source='data.yaml',names=names)


def test_record_geometry_and_ids_are_typed():
    with pytest.raises(ValidationError):ImageRecord(path='a.png',width=-1)
    with pytest.raises(ValidationError):ImageRecord(path='')
    with pytest.raises(ValidationError):SegmentationAnnotation(class_id=0,kind='polygon',polygon=[(0.,0.),(1.,1.)],area_normalized=.2)
    with pytest.raises(ValidationError):SegmentationSample(sample_id='',split='train',image=ImageRecord(path='a.png'),annotation_path=None)


def test_missing_empty_dataset_and_record_cap_fail_explicitly(tmp_path):
    cfg=dataset(tmp_path)
    with pytest.raises(ConfigurationError,match='no supported images'):run(cfg)
    image(cfg);label(cfg);cfg.max_records=1
    with pytest.raises(ConfigurationError,match='max_records'):run(cfg)


def test_output_inside_source_is_rejected(tmp_path):
    cfg=dataset(tmp_path);cfg.output_dir=cfg.dataset_root/'out'
    with pytest.raises(ConfigurationError,match='overwrite'):run(cfg)


def test_remote_and_empty_config_paths_are_rejected(tmp_path):
    path=tmp_path/'config.yaml';path.write_text('dataset_root: "https://remote/dataset"\noutput_dir: local\n')
    with pytest.raises(ConfigurationError,match='local filesystem'):load_config(path)


def test_sanity_buffer_and_disk_index_are_bounded(tmp_path):
    cfg=dataset(tmp_path);cfg.sanity_capacity=2
    from QCI_1_Surface_Defect_Segmentation.pipeline import retain_candidate
    heap=[]
    for n in range(100):
        sample=SegmentationSample(sample_id=str(n),split='train',image=ImageRecord(path=str(n)+'.png'),annotation_path=None)
        retain_candidate(heap,sample,cfg);assert len(heap)<=2
    image(cfg);label(cfg);_,metadata=read_mapping(cfg);inventory=Inventory(tmp_path/'index.sqlite',cfg,metadata)
    try:
        assert inventory.connection.execute('PRAGMA cache_size').fetchone()[0]==-2048
        assert inventory.connection.execute('PRAGMA temp_store').fetchone()[0]==1
    finally:inventory.close()
