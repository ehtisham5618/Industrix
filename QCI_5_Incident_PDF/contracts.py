"""Validated report snapshots, local configuration and controlled export results."""
from datetime import datetime, timezone
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from . import VERSION

class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

Text = Annotated[str, Field(min_length=1, max_length=512)]
class Evidence(Contract):
    role: Literal['Evidence image', 'Model Attribution Heatmap']
    path: str
    sha256: Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')] | None = None
    context: str = 'Acquisition timestamp unavailable'

class Transition(Contract):
    timestamp: str
    state: str
    detail: str | None = None

class Telemetry(Contract):
    timestamp: datetime
    context: Literal['Telemetry at report generation time'] = 'Telemetry at report generation time'
    edge_status: str
    cloud_status: str
    mode: str
    pending: int = Field(ge=0)
    cpu_percent: float | None = Field(default=None, ge=0, le=100)
    process_rss_mb: float | None = Field(default=None, ge=0)
    policy_version: str = 'qci4-edge-policy-v1'

class ReportData(Contract):
    incident_id: Text
    event_id: Text
    timestamp: datetime
    defect_class: Text
    severity: Literal['info', 'warning', 'critical']
    state: Text
    source_id: Text | None = None
    location: Text | None = None
    sample_id: Text | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    model_version: Text | None = None
    policy_version: Text | None = None
    bbox: tuple[float, float, float, float] | None = None
    track_id: int | None = None
    delivery: str | None = None
    delivery_attempts: int | None = Field(default=None, ge=0)
    operator_name: str | None = Field(default=None, max_length=1000)
    operator_notes: str | None = Field(default=None, max_length=100000)
    corrective_action: str | None = Field(default=None, max_length=100000)
    is_sample: bool = False
    evidence: list[Evidence] = Field(default_factory=list, max_length=2)
    transitions: list[Transition] = Field(default_factory=list, max_length=200)
    telemetry: Telemetry | None = None
    warnings: list[str] = Field(default_factory=list, max_length=32)
    @field_validator('timestamp')
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('Timezone-aware incident timestamp required')
        return value.astimezone(timezone.utc)

class Config(Contract):
    output_dir: str = 'reports/incidents'
    title: str = 'IndusriX Industrial Quality Incident Report'
    report_version: str = VERSION
    quality_database: str | None = None
    evidence_index: str | None = None
    evidence_roots: list[str] = Field(default_factory=lambda: [
        'data/snapshots', 'reports/qci2/heatmaps',
        'QCI_3_Severity_IoT/runtime/heatmaps',
        'QCI_1_Surface_Defect_Segmentation/runtime/segmentation_dataset'])
    include_heatmap: bool = True
    include_telemetry: bool = True
    max_image_bytes: int = Field(default=16*1024*1024, ge=1024, le=32*1024*1024)
    max_image_pixels: int = Field(default=16000000, ge=1, le=32000000)
    @field_validator('title', 'report_version')
    @classmethod
    def short(cls, value):
        if not value.strip() or len(value)>128: raise ValueError('Invalid report title/version')
        return value

class ExportResult(Contract):
    status: Literal['SUCCESS', 'FAILED']
    incident_id: str
    output_path: str | None = None
    size_bytes: int = 0
    latency_ms: float = Field(ge=0)
    lookup_ms: float = Field(default=0, ge=0)
    evidence_ms: float = Field(default=0, ge=0)
    render_ms: float = Field(default=0, ge=0)
    write_ms: float = Field(default=0, ge=0)
    sha256: str | None = None
    warnings: list[str] = Field(default_factory=list)
    report_version: str = VERSION
    error: Literal['INVALID_INPUT', 'NOT_FOUND', 'STORAGE_UNAVAILABLE', 'EXPORT_FAILED'] | None = None
