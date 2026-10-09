"""Strict contracts; classifier confidence and attribution are not risk scores."""
from __future__ import annotations
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID
from typing import Annotated, Literal
from urllib.parse import urlsplit
import ipaddress
import json
from pydantic import Field, StrictInt, field_validator, model_validator
from QCI_1_Surface_Defect_Segmentation.contracts import Contract
from QCI_2_Defect_Classifier.contracts import PredictionResult
from SED_2_Alert_Escalation.scripts.models import Severity, EventState

Identifier = Annotated[str, Field(min_length=1,max_length=128,pattern=r'^[A-Za-z0-9_.:-]+$')]
Seconds = Annotated[float,Field(ge=0,le=86400,allow_inf_nan=False)]

class Delivery(str,Enum):
    DISABLED='DISABLED'
    PENDING='PENDING'
    ACKNOWLEDGED='ACKNOWLEDGED'
    FAILED='FAILED'
    DELIVERY_UNKNOWN='DELIVERY_UNKNOWN'

class Event(Contract):
    source_id: Identifier
    event_id: Identifier
    sequence: Annotated[StrictInt,Field(ge=0)]
    observed_at: datetime
    prediction: PredictionResult

    @field_validator('prediction',mode='before')
    @classmethod
    def bounded_prediction(cls,value):
        data=value.model_dump() if isinstance(value,PredictionResult) else value
        if isinstance(data,dict):
            if len(data.get('class_scores',[]))>2 or len(data.get('warnings',[]))>16:
                raise ValueError('Prediction lists exceed alarm metadata limits')
            if any(not isinstance(w,str) or len(w)>512 for w in data.get('warnings',[])):
                raise ValueError('Prediction warnings exceed alarm metadata limits')
            if not isinstance(data.get('sample_id'),str) or not 0<len(data['sample_id'])<=512:
                raise ValueError('Invalid sample identity length')
        return value

    @field_validator('observed_at')
    @classmethod
    def aware(cls,value):
        if value.tzinfo is None or value.utcoffset() is None:raise ValueError('Timezone-aware timestamp required')
        return value.astimezone(timezone.utc)

    @model_validator(mode='after')
    def success(self):
        p=self.prediction
        if p.status!='SUCCESS':raise ValueError('Alarm input must be a successful QCI-2 result')
        if p.predicted_class_id != max(range(2),key=lambda i:p.class_scores[i].score):
            raise ValueError('Predicted class is not the score argmax')
        # Bound metadata even though no images/tensors are retained by the engine.
        if len(p.model_dump_json())>32768:raise ValueError('Prediction metadata exceeds 32 KiB')
        return self

class Rule(Contract):
    initial: Severity
    warning_after_seconds: Seconds | None=None
    critical_after_seconds: Seconds | None=None
    source_overrides: dict[Identifier,Severity]=Field(default_factory=dict)

    @model_validator(mode='after')
    def order(self):
        w,c=self.warning_after_seconds,self.critical_after_seconds
        if w is not None and c is not None and c<w:raise ValueError('Critical threshold precedes Warning')
        if len(self.source_overrides)>64:raise ValueError('Too many source overrides')
        return self

class WebhookConfig(Contract):
    enabled: bool=False
    url: str | None=None
    token_environment: Annotated[str,Field(pattern=r'^[A-Z][A-Z0-9_]{0,63}$')]='QCI3_SIREN_TOKEN'
    timeout_seconds: Annotated[float,Field(gt=0,le=5,allow_inf_nan=False)]=1
    attempts: Annotated[StrictInt,Field(ge=1,le=3)]=3
    backoff_seconds: Annotated[float,Field(ge=0,le=1,allow_inf_nan=False)]=.1
    receiver_idempotent: bool=False

    @model_validator(mode='after')
    def endpoint(self):
        if self.enabled and not self.url:raise ValueError('Enabled webhook requires an explicit local URL')
        if self.url:
            if len(self.url)>4096 or any(ord(char)<=32 for char in self.url):raise ValueError('Invalid URL length or control characters')
            u=urlsplit(self.url)
            if u.scheme not in ('http','https') or not u.hostname or u.username or u.password or u.query or u.fragment:
                raise ValueError('Expected HTTP(S) URL without credentials, query or fragment')
            # Numeric address avoids DNS rebinding/cloud dependency. Explicit LAN/loopback only.
            try:ip=ipaddress.ip_address(u.hostname)
            except ValueError as exc:raise ValueError('Use a numeric loopback or private LAN IP') from exc
            if not (ip.is_loopback or ip.is_private) or ip.is_unspecified or ip.is_multicast:
                raise ValueError('Webhook must use loopback or private LAN')
            if u.port is not None and not 1<=u.port<=65535:raise ValueError('Invalid port')
        if self.attempts>1 and self.enabled and not self.receiver_idempotent:
            raise ValueError('Retries require receiver Idempotency-Key support')
        return self

class Config(Contract):
    policy_version: Identifier='qci3-research-v1'
    expected_model_version: Identifier='qci2-kolektor-resnet18-v1'
    database: str='Backend/data/events.db'
    rules: dict[Literal['normal','defect'],Rule]=Field(default_factory=lambda:{
        'normal':Rule(initial=Severity.INFO), 'defect':Rule(initial=Severity.WARNING)})
    webhook: WebhookConfig=Field(default_factory=WebhookConfig)
    active_capacity: Annotated[StrictInt,Field(ge=1,le=4096)]=512
    record_capacity: Annotated[StrictInt,Field(ge=1,le=100000)]=10000
    outbox_capacity: Annotated[StrictInt,Field(ge=1,le=4096)]=256
    resolved_ttl_seconds: Annotated[float,Field(ge=1,le=31536000,allow_inf_nan=False)]=86400
    audit_capacity: Annotated[StrictInt,Field(ge=1,le=1000000)]=50000

    @model_validator(mode='after')
    def valid(self):
        if set(self.rules)!={'normal','defect'}:raise ValueError('Both actual QCI-2 classes need explicit rules')
        if self.record_capacity<self.active_capacity:raise ValueError('Record capacity smaller than active capacity')
        if not self.database.strip() or '://' in self.database or self.database.startswith(('\\\\','//')):
            raise ValueError('Database must be a local path')
        return self

class Status(Contract):
    source_id: Identifier
    event_id: Identifier
    sample_id: str
    state: EventState
    severity: Severity
    first_seen: datetime
    last_seen: datetime
    last_transition: datetime
    sequence: int
    model_version: str
    policy_version: str
    class_name: Literal['normal','defect']
    confidence: float
    reason: str
    actions: list[str]
    delivery: Delivery=Delivery.DISABLED
    delivery_id: str | None=None
    delivery_attempts: int=0
    last_http_status: int | None=None
    last_delivery_error: str | None=None
    decision_latency_ms: Annotated[float,Field(ge=0,allow_inf_nan=False)]=0
    transition_latency_ms: Annotated[float,Field(ge=0,allow_inf_nan=False)]=0
    local_action_latency_ms: Annotated[float,Field(ge=0,allow_inf_nan=False)]=0
    duplicate: bool=False

class WebhookPayload(Contract):
    delivery_id: UUID
    source_id: Identifier
    event_id: Identifier
    sample_id: str
    severity: Literal['critical']='critical'
    action: Literal['ACTIVATE_SIREN']='ACTIVATE_SIREN'
    model_version: str
    policy_version: str
    observed_at: datetime
    class_name: Literal['normal','defect']
    confidence: Annotated[float,Field(ge=0,le=1,allow_inf_nan=False)]

class Acknowledgement(Contract):
    delivery_id: UUID
    acknowledged: Literal[True]

class Resolve(Contract):
    source_id: Identifier
    event_id: Identifier
    observed_at: datetime
    _aware=field_validator('observed_at')(Event.aware.__func__)

def parse_config(text:str)->Config:
    """Reject duplicate JSON rule keys instead of silently accepting the last one."""
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('Duplicate configuration key: '+key)
            result[key]=value
        return result
    if len(text.encode('utf-8'))>65536:raise ValueError('Alarm configuration exceeds 64 KiB')
    return Config.model_validate(json.loads(text,object_pairs_hook=unique))
