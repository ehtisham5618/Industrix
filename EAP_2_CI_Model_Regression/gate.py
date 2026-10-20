"""EAP-2 regression contracts and quality gate (Pydantic v2).

Status vocabulary: PASS / FAIL / NOT_VERIFIED / UNDEFINED_THRESHOLD.
NOT_VERIFIED is never promoted to PASS, and a baseline is never generated
from, or updated by, an ordinary test run.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Status = Literal["PASS", "FAIL", "NOT_VERIFIED", "UNDEFINED_THRESHOLD"]
METRICS = ("precision", "recall", "map50", "map50_95")


class RegressionError(RuntimeError):
    """Actionable configuration/artifact error."""


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def _fraction(value: float) -> float:
    if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f"metric must be a finite fraction in [0, 1], got {value!r}")
    return float(value)


# ---- Output contract (mirrors Backend/main.py POST /predict) -------------------------
class Coordinates(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x1: float
    y1: float
    x2: float
    y2: float

    @model_validator(mode="after")
    def ordered_finite(self):
        values = (self.x1, self.y1, self.x2, self.y2)
        if not all(math.isfinite(v) for v in values) or min(values) < 0:
            raise ValueError("coordinates must be finite and non-negative")
        if self.x2 <= self.x1 or self.y2 <= self.y1:
            raise ValueError("box must satisfy x2 > x1 and y2 > y1")
        return self


class Detection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    class_id: int = Field(ge=0)
    class_name: str = Field(min_length=1)
    confidence: float
    coordinates: Coordinates

    @field_validator("confidence")
    @classmethod
    def valid_confidence(cls, value):
        if not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("confidence must be finite and in [0, 1]")
        return value


class PredictResponse(BaseModel):
    filename: str
    detections: list[Detection]


def validate_response(payload: dict, class_map: dict[int, str], width: int, height: int) -> PredictResponse:
    """Contract + class-map + image-bounds validation for a /predict style payload."""
    response = PredictResponse.model_validate(payload)
    for item in response.detections:
        if class_map.get(item.class_id) != item.class_name:
            raise ValueError(f"class {item.class_id}:{item.class_name!r} not in the verified class map")
        c = item.coordinates
        if c.x2 > width + 1 or c.y2 > height + 1:
            raise ValueError("box exceeds image bounds")
    return response


# ---- Baseline manifest ---------------------------------------------------------------
class EvaluationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    imgsz: int = Field(gt=0)
    batch: int = Field(gt=0)
    conf: float = Field(ge=0, le=1)
    iou: float = Field(gt=0, le=1)


class MetricSet(BaseModel):
    precision: float
    recall: float
    map50: float
    map50_95: float

    @field_validator(*METRICS, mode="before")
    @classmethod
    def valid_fraction(cls, value):
        return _fraction(value)


class BaselineManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    baseline_id: str
    model_version: str
    architecture: str
    backend: str
    artifact_path: str
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    class_map: dict[int, str]
    dataset_id: str
    dataset_split: str
    dataset_archive_sha256: Optional[str] = None
    dataset_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_counts: dict
    evaluation: EvaluationSettings
    inference_conf: float = Field(ge=0, le=1)
    metrics: MetricSet
    per_class_ap50: dict[str, float]
    source: str
    measured_environment: dict
    reviewed_by: Optional[str] = None
    notes: list[str] = []

    @model_validator(mode="after")
    def consistent(self):
        if sorted(self.class_map) != list(range(len(self.class_map))):
            raise ValueError("class ids must be contiguous from 0")
        if set(self.per_class_ap50) - set(self.class_map.values()):
            raise ValueError("per-class metrics reference unknown classes")
        for value in self.per_class_ap50.values():
            _fraction(value)
        return self


def load_manifest(path: Path) -> BaselineManifest:
    path = Path(path)
    if not path.is_file():
        raise RegressionError(f"Baseline manifest not found: {path}. Real-model regression is NOT_VERIFIED without it.")
    return BaselineManifest.model_validate_json(path.read_text(encoding="utf-8"))


# ---- Thresholds ----------------------------------------------------------------------
class Threshold(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric: str
    kind: Literal["min_absolute", "max_drop_pp", "max_value"]
    value: Optional[float] = None
    enforce: bool
    source: str


class ThresholdPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str
    thresholds: list[Threshold]


# ---- Report --------------------------------------------------------------------------
class Check(BaseModel):
    name: str
    category: Literal["code", "artifact", "inference", "quality", "performance", "offline"]
    status: Status
    detail: str
    measured: Optional[dict] = None


class RegressionReport(BaseModel):
    suite: str = "EAP-2"
    status: Status
    code_status: Status
    model_release_status: Status
    model_id: Optional[str] = None
    model_version: Optional[str] = None
    model_sha256: Optional[str] = None
    baseline_id: Optional[str] = None
    dataset_fingerprint: Optional[str] = None
    checks: list[Check]
    metrics: dict = {}
    regressions: list[dict] = []
    thresholds: dict = {}
    environment: dict = {}
    limitations: list[str] = []


def overall(statuses: list[str]) -> Status:
    if "FAIL" in statuses:
        return "FAIL"
    if "NOT_VERIFIED" in statuses:
        return "NOT_VERIFIED"
    if "UNDEFINED_THRESHOLD" in statuses:
        return "UNDEFINED_THRESHOLD"
    return "PASS"


# ---- Comparison ----------------------------------------------------------------------
def verify_artifact(path: Path, manifest: BaselineManifest) -> Check:
    path = Path(path)
    if not path.is_file():
        return Check(name="artifact_hash", category="artifact", status="NOT_VERIFIED",
                     detail=f"Model artifact missing at {path}; weights are not stored in Git")
    actual = sha256_file(path)
    if actual != manifest.artifact_sha256:
        return Check(name="artifact_hash", category="artifact", status="FAIL",
                     detail=f"SHA256 {actual} does not match baseline {manifest.artifact_sha256}",
                     measured=dict(sha256=actual))
    return Check(name="artifact_hash", category="artifact", status="PASS", detail="SHA256 matches baseline manifest",
                 measured=dict(sha256=actual))


def compare_class_map(model_names: dict, manifest: BaselineManifest) -> Check:
    names = {int(k): v for k, v in dict(model_names).items()}
    if names != manifest.class_map:
        changed = {k: (manifest.class_map.get(k), names.get(k)) for k in set(names) | set(manifest.class_map)
                   if names.get(k) != manifest.class_map.get(k)}
        return Check(name="class_map", category="artifact", status="FAIL",
                     detail=f"Class map differs from baseline: {changed}")
    return Check(name="class_map", category="artifact", status="PASS",
                 detail=f"{len(names)} classes identical to baseline (ids and names)")


def compare_metrics(candidate: dict, manifest: BaselineManifest, policy: ThresholdPolicy,
                    candidate_settings: dict, candidate_fingerprint: str) -> tuple[list[Check], list[dict], dict]:
    """Compare a measured candidate against the accepted baseline; deltas in percentage points."""
    if candidate_fingerprint != manifest.dataset_fingerprint:
        return [Check(name="quality_dataset", category="quality", status="FAIL",
                      detail="Evaluation dataset fingerprint differs from the baseline; results are not comparable")], [], {}
    if EvaluationSettings.model_validate(candidate_settings) != manifest.evaluation:
        return [Check(name="quality_settings", category="quality", status="FAIL",
                      detail="Evaluation settings differ from the baseline")], [], {}
    measured = MetricSet.model_validate({k: candidate.get(k) for k in METRICS})
    per_class = {k: _fraction(v) for k, v in candidate.get("per_class_ap50", {}).items()}
    missing = set(manifest.per_class_ap50) - set(per_class)
    deltas = {k: round(100 * (getattr(measured, k) - getattr(manifest.metrics, k)), 6) for k in METRICS}
    class_deltas = {k: round(100 * (per_class[k] - v), 6) for k, v in manifest.per_class_ap50.items() if k in per_class}
    checks, regressions = [], []
    if missing:
        checks.append(Check(name="quality_per_class_coverage", category="quality", status="FAIL",
                            detail=f"Per-class metrics missing for {sorted(missing)}"))
    for t in policy.thresholds:
        if t.metric.startswith("per_class:"):
            cls = t.metric.split(":", 1)[1]
            value, delta = per_class.get(cls), class_deltas.get(cls)
        else:
            value, delta = getattr(measured, t.metric, None), deltas.get(t.metric)
        name = f"{t.kind}:{t.metric}"
        if value is None:
            checks.append(Check(name=name, category="quality", status="FAIL", detail=f"Required metric {t.metric} missing"))
            continue
        if t.value is None:
            checks.append(Check(name=name, category="quality", status="UNDEFINED_THRESHOLD",
                                detail=f"Measured {value:.6f} (Δ {delta:+.4f} pp); no approved threshold ({t.source})",
                                measured=dict(value=value, delta_pp=delta)))
            continue
        violated = (t.kind == "min_absolute" and value < t.value) or (t.kind == "max_drop_pp" and delta < -t.value)
        if violated:
            regressions.append(dict(metric=t.metric, kind=t.kind, threshold=t.value, value=value, delta_pp=delta, source=t.source,
                                    enforced=t.enforce))
        status = ("FAIL" if t.enforce else "UNDEFINED_THRESHOLD") if violated else ("PASS" if t.enforce else "UNDEFINED_THRESHOLD")
        detail = f"{t.metric}={value:.6f} Δ {delta:+.4f} pp vs {t.kind} {t.value} ({t.source})"
        if not t.enforce:
            detail += "; reference target only, not an approved release gate" + (" — VIOLATED" if violated else "")
        checks.append(Check(name=name, category="quality", status=status, detail=detail, measured=dict(value=value, delta_pp=delta)))
    return checks, regressions, dict(measured=measured.model_dump(), delta_pp=deltas, per_class_delta_pp=class_deltas)


def write_report(report: RegressionReport, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(report.model_dump(), indent=2), encoding="utf-8")
    tmp.replace(path)
