"""Typed QCI-1 adapter fixtures preserve splits and reject altered source bytes."""
from __future__ import annotations
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import numpy as np
import pytest
from PIL import Image
from QCI_1_Surface_Defect_Segmentation.contracts import DatasetConfig
from QCI_1_Surface_Defect_Segmentation.pipeline import run
from QCI_1_Surface_Defect_Segmentation.errors import InvalidSampleError
from QCI_2_Defect_Classifier.common import TASK
from QCI_2_Defect_Classifier.contracts import TrainingConfig
from QCI_2_Defect_Classifier.data import ManifestDataset,loader


@pytest.fixture
def adapter_fixture():
    """Small synthetic image/mask files go through actual QCI-1 fixture ingestion."""
    (TASK/'runtime').mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(dir=TASK/'runtime') as directory:
        root=Path(directory);data=root/'source';data.mkdir()
        (data/'data.yaml').write_text('nc: 1\nnames: [defect]\ntrain: images/train\nval: images/val\ntest: images/test\n')
        rng=np.random.default_rng(42)
        for split in ('train','val','test'):
            for positive in (0,1):
                image=data/'images'/split/f'sample{positive}.png';mask=data/'masks'/split/f'sample{positive}.png'
                image.parent.mkdir(parents=True,exist_ok=True);mask.parent.mkdir(parents=True,exist_ok=True)
                Image.fromarray(rng.integers(0,255,(16,12,3),dtype=np.uint8)).save(image)
                Image.fromarray(np.full((16,12),positive,dtype=np.uint8)).save(mask)
        output=root/'manifest'
        result=run(DatasetConfig(dataset_root=data,output_dir=output,annotation_format='indexed_mask',annotation_dir='masks',annotation_extension='.png',max_annotation_bytes=16000,write_processed=False))
        assert result.status=='SUCCESS'
        config=TrainingConfig(manifest=output/'dataset_manifest.json',records=output/'samples.jsonl',output_dir=root/'training',starting_weights=root/'unused.pt',starting_sha256='0'*64,height=64,width=64,batch_size=2)
        yield config,data


def test_adapter_labels_bounded_loader_and_untouched_splits(adapter_fixture) -> None:
    config,_=adapter_fixture
    for split in ('train','val','test'):
        dataset=ManifestDataset(config,split);images,labels,ids=next(iter(loader(dataset,False,42)))
        assert images.shape==(2,3,64,64) and labels.tolist()==[0,1]
        assert all(s.startswith(split+'/') for s in ids)
        batches=loader(dataset,False,42);assert batches.num_workers==0 and batches.prefetch_factor is None and not batches.pin_memory


def test_adapter_rejects_source_image_and_mask_mutation(adapter_fixture) -> None:
    config,data=adapter_fixture;dataset=ManifestDataset(config,'train')
    (data/'images/train/sample0.png').write_bytes(b'changed')
    with pytest.raises(InvalidSampleError):dataset[0]
    (data/'masks/train/sample1.png').write_bytes(b'changed')
    with pytest.raises(ValueError,match='mask changed'):dataset[1]


def test_manifest_count_mismatch_rejected(adapter_fixture) -> None:
    config,_=adapter_fixture
    lines=config.records.read_text().splitlines();config.records.write_text('\n'.join(lines[:-1])+'\n')
    with pytest.raises(ValueError,match='counts mismatch'):ManifestDataset(config,'train')


def test_unvalidated_or_duplicate_record_rejected(adapter_fixture) -> None:
    config,_=adapter_fixture
    original=config.records.read_text();line=original.splitlines()[0]
    config.records.write_text(original+line+'\n')
    with pytest.raises(ValueError,match='Duplicate'):ManifestDataset(config,'train')
    sample=json.loads(line);sample['source_valid']=False;sample['segmentation_valid']=False
    config.records.write_text(json.dumps(sample)+'\n')
    with pytest.raises(ValueError,match='eligible'):ManifestDataset(config,'train')


def test_bounded_metadata_limit_and_augmentation_shape(adapter_fixture) -> None:
    config,_=adapter_fixture;config.max_samples=2
    with pytest.raises(ValueError,match='metadata limit'):ManifestDataset(config,'train')
    config.max_samples=10;dataset=ManifestDataset(config,'train',True)
    image,label,_=dataset[1];assert image.shape==(3,64,64) and label.item()==1
