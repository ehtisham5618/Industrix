"""Further ingestion boundary checks for malformed files and mutable inputs."""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image
from pydantic import ValidationError
from QCI_1_Surface_Defect_Segmentation.config import ROOT,load_config
from QCI_1_Surface_Defect_Segmentation.contracts import ImageRecord,SegmentationSample
from QCI_1_Surface_Defect_Segmentation.errors import ConfigurationError
from QCI_1_Surface_Defect_Segmentation.pipeline import run
from tests.test_qci1_ingestion import dataset,image,label

@pytest.fixture
def tmp_path():
    base=ROOT/'QCI_1_Surface_Defect_Segmentation/runtime';base.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='edges_',dir=base) as value:yield Path(value)

def test_malformed_yaml_is_a_configuration_error(tmp_path):
    path=tmp_path/'bad.yaml';path.write_text('dataset_root: [unterminated')
    with pytest.raises(ConfigurationError):load_config(path)

def test_serialized_box_cannot_claim_segmentation_readiness():
    with pytest.raises(ValidationError):SegmentationSample(sample_id='train/a',split='train',image=ImageRecord(path='a.png',width=10,height=10),
        annotation_path='a.txt',annotation_kind='box',source_valid=True,segmentation_valid=True)

def test_bad_png_crc_is_structured_and_does_not_abort_scan(tmp_path):
    cfg=dataset(tmp_path);path=image(cfg);label(cfg)
    data=bytearray(path.read_bytes());data[29]^=255;path.write_bytes(data)
    result=run(cfg);assert result.statistics.issues['CORRUPTED_IMAGE']==1

def test_invalid_utf8_annotation_is_reported(tmp_path):
    cfg=dataset(tmp_path);image(cfg);p=label(cfg);p.write_bytes(b'\xff\xfe')
    result=run(cfg);assert result.statistics.issues['MALFORMED_ANNOTATION']==1

def test_annotation_change_between_scan_and_export_is_rejected(tmp_path):
    cfg=dataset(tmp_path);image(cfg);path=label(cfg)
    from QCI_1_Surface_Defect_Segmentation.validation import decode_image
    calls=0
    def modified(*args,**kwargs):
        nonlocal calls
        calls+=1
        if calls==2:path.write_text('1 .1 .1 .9 .1 .9 .9 .1 .9')
        return decode_image(*args,**kwargs)
    with patch('QCI_1_Surface_Defect_Segmentation.pipeline.decode_image',side_effect=modified):result=run(cfg)
    assert result.statistics.issues['SOURCE_CHANGED_DURING_SCAN']==1
    assert result.statistics.valid_segmentation_samples==0 and not (cfg.output_dir/'processed').exists()

def test_source_bytes_remain_unchanged(tmp_path):
    cfg=dataset(tmp_path);p=image(cfg);a=label(cfg,'0.0 .5 .5 .5 .5');before=(p.read_bytes(),a.read_bytes())
    run(cfg);assert before==(p.read_bytes(),a.read_bytes())

def test_missing_dataset_metadata_is_not_invented(tmp_path):
    cfg=dataset(tmp_path);(cfg.dataset_root/'data.yaml').unlink();image(cfg);label(cfg)
    with pytest.raises(ConfigurationError):run(cfg)

def test_missing_root_is_explicit(tmp_path):
    cfg=dataset(tmp_path);cfg.dataset_root=tmp_path/'nonexistent'
    with pytest.raises(ConfigurationError,match='does not exist'):run(cfg)
