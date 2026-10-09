"""Consume QCI-1 typed records; never ingest, relabel or reshuffle its dataset."""
from __future__ import annotations
import random
from pathlib import Path
from collections import Counter
import numpy as np
import torch
from torch.utils.data import Dataset, DataLoader
from PIL import Image,ImageEnhance
from QCI_1_Surface_Defect_Segmentation.config import inside
from QCI_1_Surface_Defect_Segmentation.config import local_path
from QCI_1_Surface_Defect_Segmentation.contracts import DatasetConfig,ProcessingResult,SegmentationSample
from QCI_1_Surface_Defect_Segmentation.preprocessing import prepare
from QCI_1_Surface_Defect_Segmentation.validation import decode_image,file_hash
from .contracts import TrainingConfig


def image_label(sample: SegmentationSample) -> int:
    """Declared normal=verified empty mask; defect=positive canonical mask layer."""
    if not sample.source_valid or not sample.segmentation_valid or sample.annotation_kind!='indexed_mask':raise ValueError('QCI-1 sample is not eligible real segmentation')
    if len(sample.annotations)>1:raise ValueError('Expected one binary semantic mask layer, not multiple objects/classes')
    if any(a.class_id!=0 or a.kind!='indexed_mask' or not a.foreground_pixels for a in sample.annotations):raise ValueError('Unexpected QCI-1 defect classes/pixels')
    if sample.empty_annotation!= (len(sample.annotations)==0):raise ValueError('Contradictory mask-derived label')
    return int(bool(sample.annotations))


class ManifestDataset(Dataset[tuple[torch.Tensor,torch.Tensor,str]]):
    """Bounded metadata identities; image tensors decoded on demand, workers0."""
    def __init__(self, config: TrainingConfig, split: str, augment: bool=False) -> None:
        self.config=config;self.augment=augment
        if config.manifest.stat().st_size>2_000_000:raise ValueError('Manifest exceeds2MB metadata limit')
        self.manifest=ProcessingResult.model_validate_json(config.manifest.read_text(encoding='utf-8'))
        if self.manifest.status!='SUCCESS' or self.manifest.annotation_format!='indexed_mask' or self.manifest.class_mapping.names!={0:'defect'}:raise ValueError('Expected successful binary QCI-1 segmentation manifest')
        self.root=local_path(config.dataset_root_override or Path(self.manifest.dataset_root))
        if self.manifest.source_metadata_sha256 and file_hash(inside(self.root/self.manifest.class_mapping.source,self.root))!=self.manifest.source_metadata_sha256:raise ValueError('QCI-1 canonical source mapping changed')
        self.decode_config=DatasetConfig(dataset_root=self.root,output_dir=config.output_dir,target_height=config.height,target_width=config.width,max_pixels=2_000_000)
        self.rows:list[SegmentationSample]=[];total=0;metadata_bytes=0;seen:set[str]=set();counts=Counter()
        with config.records.open(encoding='utf-8') as stream:
            for line in iter(lambda:stream.readline(64_001),''):
                if len(line)>64_000:raise ValueError('QCI-1 record exceeds bounded size')
                metadata_bytes+=len(line.encode('utf-8'))
                if metadata_bytes>64_000_000:raise ValueError('QCI-1 metadata exceeds64MB limit')
                total+=1
                if total>config.max_samples:raise ValueError('QCI-1 inventory exceeds metadata limit')
                sample=SegmentationSample.model_validate_json(line);image_label(sample)
                if sample.sample_id in seen:raise ValueError('Duplicate QCI-1 sample identity')
                seen.add(sample.sample_id);counts[sample.split]+=1
                if sample.split==split:self.rows.append(sample)
        if total!=self.manifest.statistics.total_samples or dict(counts)!=self.manifest.statistics.split_counts:raise ValueError('QCI-1 manifest/record split counts mismatch')
        if not self.rows:raise ValueError('Requested QCI-1 split is empty')

    def __len__(self) -> int:
        """Number of verified metadata rows in this unchanged split."""
        return len(self.rows)

    def __getitem__(self, index: int) -> tuple[torch.Tensor,torch.Tensor,str]:
        """Load one immutable source image; masks only establish labels."""
        row=self.rows[index];path=inside(self.root/row.image.path,self.root)
        image,record=decode_image(path,self.decode_config)
        if record.sha256!=row.image.sha256:raise ValueError('QCI-1 source image changed')
        if file_hash(inside(self.root/str(row.annotation_path),self.root))!=row.annotation_sha256:raise ValueError('QCI-1 source mask changed')
        if self.augment:
            if random.random()<self.config.horizontal_flip:image=np.ascontiguousarray(image[:,::-1])
            magnitude=self.config.brightness_contrast
            picture=Image.fromarray(image)
            picture=ImageEnhance.Brightness(picture).enhance(1+random.uniform(-magnitude,magnitude))
            picture=ImageEnhance.Contrast(picture).enhance(1+random.uniform(-magnitude,magnitude))
            image=np.asarray(picture)
        tensor=torch.from_numpy(prepare(image,None,self.decode_config).tensor())
        tensor=(tensor-torch.tensor([.485,.456,.406])[:,None,None])/torch.tensor([.229,.224,.225])[:,None,None]
        return tensor,torch.tensor(image_label(row),dtype=torch.long),row.sample_id


def loader(dataset: ManifestDataset, shuffle: bool, seed: int) -> DataLoader:
    """One in-process batch; no worker processes, pinned memory or prefetch queue."""
    generator=torch.Generator().manual_seed(seed)
    return DataLoader(dataset,batch_size=dataset.config.batch_size,shuffle=shuffle,num_workers=0,pin_memory=False,generator=generator)
