"""Pydantic v2 local configuration, prediction and measured evaluation contracts."""
from __future__ import annotations
from pathlib import Path
from typing import Annotated, Literal, Self
from pydantic import Field, StrictInt, field_validator, model_validator
from QCI_1_Surface_Defect_Segmentation.contracts import Contract, PositiveInt, UnitFloat

Finite = Annotated[float, Field(allow_inf_nan=False)]
Milliseconds = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class TrainingConfig(Contract):
    """Explicit bounded CPU fine-tuning; no implicit download or test tuning."""
    manifest: Path
    records: Path
    output_dir: Path
    starting_weights: Path
    starting_sha256: str
    dataset_root_override: Path | None = None
    architecture: Literal['resnet18'] = 'resnet18'
    height: Annotated[StrictInt, Field(ge=64, le=1024)] = 448
    width: Annotated[StrictInt, Field(ge=64, le=1024)] = 192
    batch_size: Annotated[StrictInt, Field(ge=1, le=32)] = 8
    epochs: Annotated[StrictInt, Field(ge=1, le=200)] = 40
    patience: PositiveInt = 8
    learning_rate: Annotated[float, Field(gt=0, le=.1, allow_inf_nan=False)] = .0001
    head_learning_rate: Annotated[float, Field(gt=0, le=.1, allow_inf_nan=False)] = .001
    weight_decay: Annotated[float, Field(ge=0, le=.1, allow_inf_nan=False)] = .0001
    seed: StrictInt = 42
    workers: Literal[0] = 0
    threads: Annotated[StrictInt, Field(ge=1, le=8)] = 2
    pin_memory: Literal[False] = False
    device: Literal['cpu'] = 'cpu'
    optimizer: Literal['AdamW'] = 'AdamW'
    scheduler: Literal['CosineAnnealingLR'] = 'CosineAnnealingLR'
    class_weights: Literal['inverse_train_frequency'] = 'inverse_train_frequency'
    horizontal_flip: UnitFloat = .5
    brightness_contrast: Annotated[float, Field(ge=0, le=.2, allow_inf_nan=False)] = .08
    low_confidence_threshold: UnitFloat = .65
    max_samples: Annotated[StrictInt, Field(ge=1, le=10000)] = 10000

    @field_validator('manifest','records','output_dir','starting_weights','dataset_root_override', mode='before')
    @classmethod
    def local_inputs(cls, value: object) -> object:
        """Reject URLs/UNC/empty paths before Path coercion."""
        if isinstance(value,str) and (not value.strip() or '://' in value or value.startswith(('\\\\','//'))):
            raise ValueError('Expected nonempty local path')
        return value

    @field_validator('starting_sha256')
    @classmethod
    def hash_format(cls, value: str) -> str:
        """Require an exact SHA256 checkpoint identity."""
        if len(value)!=64 or any(x not in '0123456789abcdef' for x in value):raise ValueError('Invalid SHA256')
        return value

    @model_validator(mode='after')
    def bounded_pixels(self) -> Self:
        """Bound batch image memory independently of source dataset size."""
        if self.width*self.height>524288:raise ValueError('Input pixel budget exceeded')
        return self


class PredictionRequest(Contract):
    """Single local image; explicit optional attribution class and output folder."""
    image: Path
    heatmap: bool = True
    target_class: Annotated[StrictInt, Field(ge=0,le=1)] | None = None
    output_dir: Path | None = None

    @field_validator('image','output_dir',mode='before')
    @classmethod
    def local_inputs(cls, value: object) -> object:
        """Reject remote inputs before coercion."""
        return TrainingConfig.local_inputs(value)


class ClassScore(Contract):
    """Softmax confidence, not a calibrated risk probability."""
    class_id: Literal[0,1]
    class_name: Literal['normal','defect']
    score: UnitFloat

    @model_validator(mode='after')
    def mapping_consistent(self) -> Self:
        """A score cannot associate a normal ID with the defect class name."""
        if self.class_name!=('normal' if self.class_id==0 else 'defect'):raise ValueError('Class ID/name mismatch')
        return self


class HeatmapResult(Contract):
    """Actual Grad-CAM target and finite normalized image-aligned artifact paths."""
    method: Literal['Grad-CAM'] = 'Grad-CAM'
    target_layer: str
    target_class_id: Literal[0,1]
    target_class_name: Literal['normal','defect']
    width: PositiveInt
    height: PositiveInt
    minimum: UnitFloat
    maximum: UnitFloat
    degenerate: bool
    raw_heatmap_path: str | None = None
    overlay_path: str | None = None
    alpha: UnitFloat = .35


class PredictionResult(Contract):
    """Failures have no invented prediction, confidence, model or artifact."""
    status: Literal['SUCCESS','FAILED']
    sample_id: str
    model_version: str | None = None
    predicted_class_id: Literal[0,1] | None = None
    predicted_class_name: Literal['normal','defect'] | None = None
    confidence: UnitFloat | None = None
    class_scores: list[ClassScore] = Field(default_factory=list)
    classifier_latency_ms: Milliseconds | None = None
    heatmap_latency_ms: Milliseconds | None = None
    combined_latency_ms: Milliseconds | None = None
    heatmap: HeatmapResult | None = None
    warnings: list[str] = Field(default_factory=list)
    error_type: str | None = None
    error_message: str | None = None

    @model_validator(mode='after')
    def status_consistency(self) -> Self:
        """Never serialize partial successes as an invented successful class."""
        if self.status=='SUCCESS' and (self.model_version is None or self.predicted_class_id is None or self.confidence is None or len(self.class_scores)!=2):
            raise ValueError('Success requires an actual model and two-class prediction')
        if self.status=='SUCCESS':
            if [s.class_id for s in self.class_scores]!=[0,1] or abs(sum(s.score for s in self.class_scores)-1)>1e-5:raise ValueError('Expected normalized two-class scores')
            if self.predicted_class_name!=('normal' if self.predicted_class_id==0 else 'defect'):raise ValueError('Prediction ID/name mismatch')
            if abs(self.confidence-self.class_scores[self.predicted_class_id].score)>1e-6:raise ValueError('Confidence mismatch')
        if self.status=='FAILED' and (self.predicted_class_id is not None or self.predicted_class_name is not None or self.confidence is not None or self.heatmap is not None or self.class_scores or self.model_version is not None):
            raise ValueError('Failure cannot carry invented successful results')
        return self


class PerClassMetrics(Contract):
    """Measured class counts and finite zero-division-safe metrics."""
    class_id: Literal[0,1]
    class_name: Literal['normal','defect']
    support: Annotated[StrictInt, Field(ge=0)]
    precision: UnitFloat
    recall: UnitFloat
    f1: UnitFloat


class EvaluationResult(Contract):
    """Exact held-out confusion matrix and macro metrics."""
    samples: PositiveInt
    accuracy: UnitFloat
    macro_precision: UnitFloat
    macro_recall: UnitFloat
    macro_f1: UnitFloat
    confusion_matrix: list[list[Annotated[StrictInt,Field(ge=0)]]]
    per_class: list[PerClassMetrics]

    @model_validator(mode='after')
    def consistent_counts(self) -> Self:
        """Keep externally supplied count contracts aligned to binary metrics."""
        if len(self.confusion_matrix)!=2 or any(len(r)!=2 for r in self.confusion_matrix):raise ValueError('Expected2x2 matrix')
        if sum(map(sum,self.confusion_matrix))!=self.samples:raise ValueError('Matrix/sample mismatch')
        if [r.class_id for r in self.per_class]!=[0,1] or any(r.support!=sum(self.confusion_matrix[r.class_id]) for r in self.per_class):raise ValueError('Per-class support mismatch')
        return self


class ModelArtifact(Contract):
    """Traceable actual selected checkpoint, initialization and dataset identity."""
    version: str
    architecture: Literal['resnet18'] = 'resnet18'
    checkpoint: str
    sha256: str
    classes: dict[int,str]
    parameters: PositiveInt
    trainable_parameters: PositiveInt
    input_height: PositiveInt
    input_width: PositiveInt
    starting_weights_sha256: str
    manifest_sha256: str
    records_sha256: str
    source_commit: str
    best_epoch: PositiveInt
