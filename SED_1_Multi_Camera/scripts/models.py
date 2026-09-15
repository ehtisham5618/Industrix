from __future__ import annotations

from dataclasses import dataclass, field
from collections import deque
from time import perf_counter
from typing import Any


ARCHITECTURE_VERSION = "ESECPU2-async-ring15-sample4-v1"


@dataclass(frozen=True)
class GeofenceConfig:
    id: str
    polygon: list[tuple[float, float]]
    classes: set[str]
    enabled: bool = True
    alert_behavior: str | None = None


@dataclass(frozen=True)
class CameraConfig:
    camera_id: str
    name: str
    source: str
    enabled: bool = True
    loop: bool = True
    sampling_fps: float | None = None
    monitored_classes: set[str] = field(default_factory=set)
    geofences: list[GeofenceConfig] = field(default_factory=list)
    sample_every: int = 4


@dataclass(frozen=True)
class FramePacket:
    camera_id: str
    frame_id: int
    timestamp: float
    frame: Any
    source_fps: float
    capture_time: float = field(default_factory=perf_counter)
    session_id: int = 0
    buffer_write_time: float = 0.0


@dataclass
class DetectionResult:
    camera_id: str
    frame_id: int
    timestamp: float
    detections: list[dict[str, Any]]
    calibrated_detections: list[dict[str, Any]] = field(default_factory=list)
    alerts: list[dict[str, Any]] = field(default_factory=list)
    escalations: list[dict[str, Any]] = field(default_factory=list)
    geofence_matches: list[dict[str, Any]] = field(default_factory=list)
    inference_time: float = 0.0
    processing_time: float = 0.0
    end_to_end_latency: float = 0.0
    raw_detections: list[dict[str, Any]] = field(default_factory=list)
    result_ready_at: float = 0.0


@dataclass
class CameraMetrics:
    captured: int = 0
    eligible: int = 0
    submitted: int = 0
    processed: int = 0
    configured_skips: int = 0
    overload_drops: int = 0
    decode_failures: int = 0
    read_attempts: int = 0
    open_failures: int = 0
    reconnect_attempts: int = 0
    reconnections: int = 0
    loop_rewinds: int = 0
    worker_crashes: int = 0
    inference_drops: int = 0
    source_fps: float = 0.0
    frame_ages_ms: deque = field(default_factory=lambda: deque(maxlen=4096))
    capture_sample_ms: deque = field(default_factory=lambda: deque(maxlen=4096))
    sample_inference_ms: deque = field(default_factory=lambda: deque(maxlen=4096))
    queue_depth_samples: deque = field(default_factory=lambda: deque(maxlen=4096))
    inference_times: deque = field(default_factory=lambda: deque(maxlen=4096))
    processing_times: deque = field(default_factory=lambda: deque(maxlen=4096))
    latencies: deque = field(default_factory=lambda: deque(maxlen=4096))
    started_at: float | None = None
    ended_at: float | None = None
    status: str = "stopped"
    last_error: str | None = None
    last_exception: dict | None = None

    @property
    def unexpected_drop_rate(self) -> float:
        if self.eligible <= 0:
            return 0.0
        return ((self.overload_drops+self.inference_drops) / self.eligible) * 100.0

    @property
    def processed_fps(self) -> float:
        if self.started_at is None:
            return 0.0
        elapsed = max(0.000001, (self.ended_at if self.ended_at is not None else perf_counter()) - self.started_at)
        return self.processed / elapsed


@dataclass
class StreamStatus:
    camera_id: str
    name: str
    enabled: bool
    status: str
    captured: int
    eligible: int
    processed: int
    overload_drops: int
    drop_rate_pct: float
    processed_fps: float
    queue_depth: int
    last_error: str | None = None
    capture_fps: float = 0.0
    read_failures: int = 0
    buffer_overruns: int = 0
    intentional_skips: int = 0
    last_frame_age_ms: float | None = None
    connected: bool = False


