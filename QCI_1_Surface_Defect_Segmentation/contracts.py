"""Pydantic v2 contracts; unknown segmentation truth is never replaced by zeros."""
from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

Split = Literal['train', 'val', 'test']
PositiveInt = Annotated[StrictInt, Field(gt=0)]
NonnegativeInt = Annotated[StrictInt, Field(ge=0)]
UnitFloat = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
Point = tuple[UnitFloat, UnitFloat]


class Contract(BaseModel):
    """Reject unknown fields and validate subsequent assignments."""
    model_config = ConfigDict(extra='forbid', validate_assignment=True)


class DatasetConfig(Contract):
    """Bounded local input, canonical source map, and explicit preprocessing."""
    dataset_root: Path
    output_dir: Path
    annotation_format: Literal['yolo', 'indexed_mask'] = 'yolo'
    metadata_file: str = 'data.yaml'
    image_dir: str = 'images'
    annotation_dir: str = 'labels'
    annotation_extension: str = '.txt'
    empty_yolo_annotation_kind: Literal['box', 'polygon'] = 'box'
    seed: StrictInt = 42
    target_width: PositiveInt = 640
    target_height: PositiveInt = 640
    max_pixels: PositiveInt = 16_777_216
    max_image_bytes: PositiveInt = 64_000_000
    max_annotation_bytes: PositiveInt = 1_000_000
    max_records: PositiveInt = 200_000
    max_instances: PositiveInt = 256
    max_polygon_points: PositiveInt = 1024
    max_depth: PositiveInt = 16
    sanity_capacity: Annotated[StrictInt, Field(ge=1, le=12)] = 6
    allow_empty_annotations: bool = True
    write_processed: bool = True
    split_ratios: tuple[UnitFloat, UnitFloat, UnitFloat] = (.8, .1, .1)

    @field_validator('dataset_root', 'output_dir', mode='before')
    @classmethod
    def nonempty_paths(cls, value: object) -> object:
        """Do not let an empty path silently become the current directory."""
        if isinstance(value,str) and not value.strip():raise ValueError('Empty local path')
        if isinstance(value,str) and ('://' in value or value.startswith(('\\\\','//'))):
            raise ValueError('Expected a local filesystem path, never a URL or UNC path')
        return value

    @field_validator('metadata_file', 'image_dir', 'annotation_dir')
    @classmethod
    def relative_names(cls, value: str) -> str:
        """Config-relative names cannot escape the dataset or use remote URLs."""
        if not value.strip() or Path(value).is_absolute() or '..' in Path(value).parts or ':' in value or '\\' in value:
            raise ValueError('Expected a nonempty relative local path')
        return value

    @model_validator(mode='after')
    def consistent(self) -> Self:
        """Keep annotation suffixes and memory-related target sizes consistent."""
        if abs(sum(self.split_ratios)-1)>1e-9:
            raise ValueError('Split ratios must sum to one')
        if self.target_width*self.target_height>self.max_pixels:
            raise ValueError('Target exceeds configured pixel limit')
        if self.annotation_format=='indexed_mask' and self.annotation_extension!='.png':
            raise ValueError('Indexed masks must explicitly use .png')
        if self.annotation_format=='yolo' and self.annotation_extension!='.txt':
            raise ValueError('YOLO annotations must use .txt')
        return self


class ClassMapping(Contract):
    """Source IDs remain canonical; only derived mask IDs reserve background zero."""
    source: str
    names: dict[NonnegativeInt, str]
    mask_background: Literal[0] = 0
    mask_offset: Literal[1] = 1

    @field_validator('names')
    @classmethod
    def canonical(cls, value: dict[int, str]) -> dict[int, str]:
        """Source IDs must be contiguous, distinct and fit an 8-bit indexed mask."""
        if not value or sorted(value)!=list(range(len(value))) or len(value)>254:
            raise ValueError('Expected contiguous source IDs 0..N-1, N<=254')
        names=[n.strip() for n in value.values()]
        if any(not n for n in names) or len(set(names))!=len(names):
            raise ValueError('Class names must be nonempty and unique')
        return {key:value[key].strip() for key in sorted(value)}


class Issue(Contract):
    """One inspectable, bounded error/warning instead of an implicit skip."""
    code: str
    stage: Literal['discovery', 'image', 'annotation', 'segmentation', 'leakage', 'preprocessing', 'configuration']
    message: str
    error_type: str | None = None


class ImageRecord(Contract):
    """Decoded source identity; dimensions are absent if decoding failed."""
    path: str
    sha256: str | None = None
    pixel_sha256: str | None = None
    width: PositiveInt | None = None
    height: PositiveInt | None = None

    @field_validator('path')
    @classmethod
    def nonempty(cls, value: str) -> str:
        """Reject empty path contracts."""
        if not value.strip(): raise ValueError('Empty image path')
        return value


class SegmentationAnnotation(Contract):
    """A source box is labelled as a box, never promoted to a defect polygon."""
    class_id: NonnegativeInt
    kind: Literal['box', 'polygon', 'indexed_mask']
    polygon: list[Point] = Field(default_factory=list)
    bbox: tuple[UnitFloat, UnitFloat, UnitFloat, UnitFloat] | None = None
    area_normalized: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] | None = None
    foreground_pixels: NonnegativeInt | None = None

    @model_validator(mode='after')
    def geometry_contract(self) -> Self:
        """Enforce the declared annotation kind and sufficient polygon vertices."""
        if self.kind=='polygon' and (len(self.polygon)<3 or not self.area_normalized or self.area_normalized<=0):
            raise ValueError('Polygon requires >=3 vertices and positive area')
        if self.kind=='box' and (self.bbox is None or self.polygon or self.foreground_pixels is not None):
            raise ValueError('Box requires bbox and has no segmentation pixels')
        if self.bbox and (self.bbox[2]<=self.bbox[0] or self.bbox[3]<=self.bbox[1]):
            raise ValueError('Bounding extent must have positive width and height')
        return self


class Transform(Contract):
    """Exact letterbox geometry and downstream normalization convention."""
    width: PositiveInt
    height: PositiveInt
    resized_width: PositiveInt
    resized_height: PositiveInt
    pad_left: NonnegativeInt
    pad_top: NonnegativeInt
    image_interpolation: Literal['area_or_linear'] = 'area_or_linear'
    mask_interpolation: Literal['nearest'] = 'nearest'
    color_order: Literal['RGB'] = 'RGB'
    normalization: Literal['float32_CHW_divide_255'] = 'float32_CHW_divide_255'
    image_storage: Literal['RGB_uint8_PNG'] = 'RGB_uint8_PNG'
    mask_storage: Literal['uint8_class_indices'] = 'uint8_class_indices'


class SegmentationSample(Contract):
    """One paired sample; source validity and segmentation readiness differ."""
    sample_id: str
    split: Split
    image: ImageRecord
    annotation_path: str | None
    annotation_sha256: str | None = None
    annotation_kind: Literal['box', 'polygon', 'indexed_mask', 'empty', 'unknown'] = 'unknown'
    annotations: list[SegmentationAnnotation] = Field(default_factory=list)
    source_valid: bool = False
    segmentation_valid: bool = False
    empty_annotation: bool = False
    issues: list[Issue] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    transform: Transform | None = None
    processed_image: str | None = None
    processed_mask: str | None = None

    @field_validator('sample_id')
    @classmethod
    def nonempty(cls, value: str) -> str:
        """Reject empty sample identities."""
        if not value.strip(): raise ValueError('Empty sample ID')
        return value

    @model_validator(mode='after')
    def trustworthy_segmentation(self) -> Self:
        """A serialized box-only record cannot falsely claim segmentation readiness."""
        if self.segmentation_valid and (not self.source_valid or self.annotation_kind in ('box','unknown') or not self.image.width or not self.image.height or any(a.kind=='box' for a in self.annotations)):
            raise ValueError('Segmentation requires valid image/annotation truth, never only boxes')
        return self


class ClassStatistics(Contract):
    """Rows/polygons or semantic mask layers; pixel truth is None for boxes."""
    class_id: NonnegativeInt
    name: str
    samples: NonnegativeInt
    instances: NonnegativeInt
    foreground_pixels: NonnegativeInt | None
    area_fraction: UnitFloat | None


class DatasetStatistics(Contract):
    """Measured counts, preserved splits and explicit unsupported segmentation."""
    total_samples: NonnegativeInt
    source_valid_samples: NonnegativeInt
    invalid_source_samples: NonnegativeInt
    valid_segmentation_samples: NonnegativeInt
    boxes_only_samples: NonnegativeInt
    empty_annotations: NonnegativeInt
    split_counts: dict[Split, NonnegativeInt]
    classes: list[ClassStatistics]
    issues: dict[str, NonnegativeInt]
    orphan_annotations: NonnegativeInt
    duplicate_sample_ids: NonnegativeInt
    duplicate_hash_groups: NonnegativeInt
    cross_split_hash_groups: NonnegativeInt
    resolution_counts: dict[str, NonnegativeInt]
    unlisted_resolution_groups: NonnegativeInt


class Performance(Contract):
    """Actual elapsed processing metrics; no unspecified SLA is invented."""
    duration_seconds: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    samples_per_second: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    mean_sample_ms: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    numeric_sla: None = None


class MemoryMetrics(Contract):
    """Measured RSS values from a dedicated comparable-workload profile."""
    start_rss_mib: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    mean_rss_mib: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    peak_rss_mib: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    end_rss_mib: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    drift_percent: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    strict_under_5_percent_pass: bool
    method: str
    workload: str


class ProcessingResult(Contract):
    """Typed CLI/core result, with genuine input and release gates kept separate."""
    version: str
    dataset_name: str | None = None
    source_metadata_sha256: str | None = None
    status: Literal['SUCCESS', 'PARTIAL', 'FAILED', 'BLOCKED']
    dataset_root: str
    annotation_format: str
    class_mapping: ClassMapping
    statistics: DatasetStatistics
    performance: Performance
    manifest_path: str
    samples_path: str
    source_sanity_path: str | None = None
    segmentation_sanity_path: str | None = None
    generated_at: datetime
    seed: StrictInt
    split_policy: str
    max_inflight_samples: Literal[1] = 1
    sanity_capacity: PositiveInt
    offline_verified: bool = False
    external_connection_attempts: NonnegativeInt = 0
    limitations: list[str] = Field(default_factory=list)
    memory: MemoryMetrics | None = None


class FatalResult(Contract):
    """Fatal configuration/storage failure, without invented dataset counts."""
    status: Literal['FAILED'] = 'FAILED'
    stage: Literal['configuration_or_storage'] = 'configuration_or_storage'
    error_type: str
    message: str
