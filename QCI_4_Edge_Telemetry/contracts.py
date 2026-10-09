"""Pydantic v2 health and outbound allowlists; no images, paths or error text."""
from __future__ import annotations
from datetime import datetime,timezone
from enum import Enum
import ipaddress
import json
from typing import Annotated,Literal
from urllib.parse import urlsplit
from pydantic import Field,StrictInt,field_validator,model_validator
from QCI_1_Surface_Defect_Segmentation.contracts import Contract

Finite=Annotated[float,Field(ge=0,allow_inf_nan=False)]
Percent=Annotated[float,Field(ge=0,le=100,allow_inf_nan=False)]
Count=Annotated[StrictInt,Field(ge=0,le=10**12)]
Identifier=Annotated[str,Field(min_length=1,max_length=128,pattern=r'^[A-Za-z0-9_.:-]+$')]

class EdgeStatus(str,Enum):
    HEALTHY='HEALTHY'
    DEGRADED='DEGRADED'
    OFFLINE_LOCAL_ONLY='OFFLINE_LOCAL_ONLY'
    ERROR='ERROR'
class CloudStatus(str,Enum):
    UNKNOWN='UNKNOWN'
    DISABLED='DISABLED'
    ONLINE='ONLINE'
    DEGRADED='DEGRADED'
    OFFLINE='OFFLINE'
    RECOVERING='RECOVERING'
class Mode(str,Enum):
    LOCAL_ONLY='LOCAL_ONLY'
    RECOVERING='RECOVERING'
    CONNECTED='CONNECTED'
class SyncState(str,Enum):
    PENDING='PENDING'
    IN_FLIGHT='IN_FLIGHT'
    DELIVERED='DELIVERED'
    FAILED_RETRYABLE='FAILED_RETRYABLE'
    FAILED_PERMANENT='FAILED_PERMANENT'
    DELIVERY_UNKNOWN='DELIVERY_UNKNOWN'

class Config(Contract):
    version: Literal['qci4-edge-policy-v1']='qci4-edge-policy-v1'
    database: str='Backend/data/events.db'
    alerts_database: str='Backend/data/events.db'
    dataset_manifest: str='reports/qci1/segmentation/dataset_manifest.json'
    sample_interval_seconds: Annotated[float,Field(ge=.1,le=60,allow_inf_nan=False)]=2
    history_capacity: Annotated[StrictInt,Field(ge=1,le=600)]=300
    inference_window: Annotated[StrictInt,Field(ge=1,le=512)]=128
    stale_inference_seconds: Annotated[float,Field(ge=1,le=86400,allow_inf_nan=False)]=60
    cloud_enabled: bool=False
    cloud_base_url: str | None=None
    health_path: str | None=None
    sync_path: str | None=None
    expected_service: Identifier='qci4-sync-v1'
    allow_telemetry_sync: bool=False
    allow_event_sync: bool=False
    token_environment: Annotated[str,Field(pattern=r'^[A-Z][A-Z0-9_]{0,63}$')]='INDUSRIX_CLOUD_TOKEN'
    request_timeout_seconds: Annotated[float,Field(gt=0,le=3,allow_inf_nan=False)]=1
    attempts: Annotated[StrictInt,Field(ge=1,le=5)]=3
    receiver_idempotent: bool=False
    health_interval_seconds: Annotated[float,Field(ge=.1,le=300,allow_inf_nan=False)]=10
    backoff_base_seconds: Annotated[float,Field(ge=.01,le=60,allow_inf_nan=False)]=1
    backoff_max_seconds: Annotated[float,Field(ge=.01,le=300,allow_inf_nan=False)]=60
    jitter_fraction: Annotated[float,Field(ge=0,le=.5,allow_inf_nan=False)]=.1
    offline_after_failures: Annotated[StrictInt,Field(ge=1,le=10)]=2
    replay_items_per_second: Annotated[float,Field(gt=0,le=100,allow_inf_nan=False)]=5
    telemetry_sync_interval_seconds: Annotated[float,Field(ge=.1,le=3600,allow_inf_nan=False)]=60
    spool_max_items: Annotated[StrictInt,Field(ge=1,le=100000)]=1000
    spool_max_payload_bytes: Annotated[StrictInt,Field(ge=1024,le=100_000_000)]=1_048_576
    item_max_bytes: Annotated[StrictInt,Field(ge=512,le=16384)]=8192
    routine_max_items: Annotated[StrictInt,Field(ge=1,le=1000)]=32
    routine_ttl_seconds: Annotated[float,Field(ge=1,le=86400,allow_inf_nan=False)]=3600
    receipt_capacity: Annotated[StrictInt,Field(ge=1,le=100000)]=10000
    receipt_ttl_seconds: Annotated[float,Field(ge=1,le=31536000,allow_inf_nan=False)]=604800
    audit_capacity: Annotated[StrictInt,Field(ge=1,le=100000)]=1000
    minimum_disk_free_bytes: Count=100_000_000

    @field_validator('database','alerts_database','dataset_manifest')
    @classmethod
    def local(cls,value):
        if not value.strip() or '://' in value or value.startswith(('\\\\','//')):raise ValueError('Local path required')
        return value

    @model_validator(mode='after')
    def policy(self):
        if self.backoff_max_seconds<self.backoff_base_seconds:raise ValueError('Backoff cap below base')
        if self.item_max_bytes>self.spool_max_payload_bytes:raise ValueError('Item budget exceeds spool budget')
        if self.cloud_enabled:
            if not self.cloud_base_url or not self.health_path or not self.sync_path:raise ValueError('Explicit endpoint and protocol paths required')
            if (self.allow_event_sync or self.allow_telemetry_sync) and not self.receiver_idempotent:
                raise ValueError('Synchronization requires a durable receiver idempotency contract')
        if self.cloud_base_url:
            u=urlsplit(self.cloud_base_url)
            if len(self.cloud_base_url)>2048 or any(ord(c)<=32 for c in self.cloud_base_url):raise ValueError('Invalid endpoint length/characters')
            if u.scheme not in ('http','https') or not u.hostname or u.username or u.password or u.query or u.fragment or u.path not in ('','/'):
                raise ValueError('Use a base HTTP(S) URL without credentials, query or path')
            # Numeric endpoints make connection deadlines independent of unbounded DNS.
            try:ip=ipaddress.ip_address(u.hostname)
            except ValueError as exc:raise ValueError('This bounded connector requires a numeric IP endpoint') from exc
            if ip.is_unspecified or ip.is_multicast:raise ValueError('Invalid destination address')
            if u.scheme=='http' and not ip.is_loopback:raise ValueError('Plain HTTP is limited to the loopback mock')
            if u.port is not None and not 1<=u.port<=65535:raise ValueError('Invalid port')
        for path in (self.health_path,self.sync_path):
            if path and (not path.startswith('/') or path.startswith('//') or len(path)>512 or '?' in path or '#' in path or any(ord(c)<=32 for c in path)):
                raise ValueError('Invalid protocol path')
        return self

class Resources(Contract):
    cpu_percent: Percent | None=None
    process_cpu_percent: Finite | None=None
    ram_used_mb: Finite | None=None
    ram_percent: Percent | None=None
    process_rss_mb: Finite | None=None
    process_uptime_seconds: Finite | None=None
    disk_used_percent: Percent | None=None
    disk_free_bytes: Count | None=None
    process_threads: Count | None=None
    process_handles: Count | None=None
    units: Literal['MiB; CPU system %, process % can exceed 100']='MiB; CPU system %, process % can exceed 100'
    errors: list[str]=Field(default_factory=list,max_length=8)

class InferenceHealth(Contract):
    status: Literal['UNKNOWN','IDLE','HEALTHY','STALE','ERROR']='UNKNOWN'
    model_status: Literal['UNKNOWN','LOADED','UNLOADED','ERROR']='UNKNOWN'
    model_loaded: bool | None=None
    model_version: str | None=None
    inference_count: Count=0
    failures: Count=0
    recent_samples: Count=0
    latency_ms: Finite | None=None
    p95_latency_ms: Finite | None=None
    combined_latency_ms: Finite | None=None
    last_inference_at: datetime | None=None
    last_error: str | None=None
    scope: Literal['instrumented QCI-2 classifier in this process']='instrumented QCI-2 classifier in this process'

class AlertHealth(Contract):
    status: Literal['UNKNOWN','HEALTHY','DEGRADED','ERROR']='UNKNOWN'
    active_info: Count | None=None
    active_warning: Count | None=None
    active_critical: Count | None=None
    retained_events: Count | None=None
    retained_transitions: Count | None=None
    webhook_acknowledged: Count | None=None
    webhook_failed: Count | None=None
    webhook_unknown: Count | None=None
    webhook_pending: Count | None=None
    last_critical_at: datetime | None=None
    last_error: str | None=None

class CloudHealth(Contract):
    status: CloudStatus=CloudStatus.DISABLED
    mode: Mode=Mode.LOCAL_ONLY
    health_check_status: Literal['UNKNOWN','ONLINE','FAILED','DISABLED']='DISABLED'
    sync_status: SyncState | None=None
    failures: Count=0
    checked_at: datetime | None=None
    last_successful_sync: datetime | None=None
    last_error: str | None=None
    last_operation_latency_ms: Finite | None=None
    next_health_check_at: datetime | None=None

class SpoolStats(Contract):
    pending: Count=0
    in_flight: Count=0
    failed_permanent: Count=0
    unknown: Count=0
    payload_bytes: Count=0
    database_bytes: Count=0
    owned_rows: Count=0
    oldest_pending_age_seconds: Finite | None=None
    delivered_total: Count=0
    overflow_total: Count=0
    routine_expired_total: Count=0
    routine_skipped_total: Count=0
    receipt_rows: Count=0

class DatasetHealth(Contract):
    status: Literal['UNKNOWN','MANIFEST_VALIDATED','ERROR']='UNKNOWN'
    version: str | None=None
    last_error: str | None=None
    basis: Literal['QCI-1 saved validation manifest; no per-sample rescan']='QCI-1 saved validation manifest; no per-sample rescan'

class Snapshot(Contract):
    timestamp: datetime
    edge_status: EdgeStatus
    resources: Resources
    dataset: DatasetHealth
    inference: InferenceHealth
    alerts: AlertHealth
    cloud: CloudHealth
    spool: SpoolStats
    events_processed: Count
    active_alerts: Count | None=None
    collection_latency_ms: Finite
    sampler_running: bool=False
    sync_worker_running: bool=False
    sample_interval_seconds: Finite
    error_categories: list[str]=Field(default_factory=list,max_length=8)
    local_ai_requires_cloud: Literal[False]=False
    outbound_telemetry_permitted: bool=False
    outbound_event_summaries_permitted: bool=False

class TelemetryPayload(Contract):
    kind: Literal['telemetry']='telemetry'
    observed_at: datetime
    cpu_percent: Percent | None
    ram_percent: Percent | None
    process_rss_mb: Finite | None
    disk_used_percent: Percent | None
    inference_count: Count
    inference_latency_ms: Finite | None
    active_alerts: Count | None
    edge_status: EdgeStatus

class EventPayload(Contract):
    kind: Literal['event_summary']='event_summary'
    observed_at: datetime
    activation_key: Annotated[str,Field(pattern=r'^[a-f0-9]{64}$')]
    transition_sequence: Count
    state: Literal['info','warning','critical','resolved']
    severity: Literal['info','warning','critical']
    model_version: Identifier
    policy_version: Identifier

Payload=Annotated[TelemetryPayload|EventPayload,Field(discriminator='kind')]

class SyncItem(Contract):
    id: Identifier
    dedupe_key: Identifier
    created_at: datetime
    payload: Payload
    payload_sha256: Annotated[str,Field(pattern=r'^[a-f0-9]{64}$')]
    status: SyncState=SyncState.PENDING
    attempt_count: Count=0
    last_attempt_at: datetime | None=None
    next_attempt_at: datetime | None=None

def parse_config(text):
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('Duplicate config key')
            result[key]=value
        return result
    if len(text.encode())>65536:raise ValueError('Configuration exceeds 64 KiB')
    return Config.model_validate(json.loads(text,object_pairs_hook=unique))

def utc(seconds):return datetime.fromtimestamp(seconds,timezone.utc)
