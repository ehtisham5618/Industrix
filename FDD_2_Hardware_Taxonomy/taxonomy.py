"""FDD-2 hazard taxonomy schema (Pydantic v2) and cross-checks against authoritative artifacts.

python -m FDD_2_Hardware_Taxonomy.taxonomy      # validate the manifest and print the result
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Literal, Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "specifications" / "hazard_taxonomy.v1.json"
SUPPORTED_SCHEMAS = {"fdd2-taxonomy-schema-v1"}


class TaxonomyError(ValueError):
    """Raised with an actionable message when the taxonomy and the repository disagree."""


class ClassSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    class_id: int = Field(ge=0)
    class_name: str = Field(min_length=1)
    stable_id: str = Field(pattern=r"^[a-z0-9]+\.[a-z_]+\.[a-z0-9_]+$")
    display_label: str = Field(min_length=1)
    domain: Literal["textile_defect", "industrial_safety", "surface_quality"]
    definition_status: Literal["approved", "provisional", "pending"]
    definition: str = Field(min_length=20)
    inclusion: list[str] = Field(min_length=1)
    exclusion: list[str] = Field(min_length=1)
    hard_negatives: list[str] = Field(min_length=1)
    annotation: str = Field(min_length=10)
    alert_class: bool
    confidence_threshold: Union[float, str]
    severity: Union[dict, str]


class ModelNamespace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: str = Field(pattern=r"^[a-z0-9-]+$")
    model_version: str
    task: str
    artifact: str
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    authoritative_sources: list[str] = Field(min_length=1)
    threshold_config: str
    severity_config: str
    dataset: str
    classes: list[ClassSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_within_namespace(self):
        ids = [c.class_id for c in self.classes]
        names = [c.class_name for c in self.classes]
        stable = [c.stable_id for c in self.classes]
        if sorted(ids) != list(range(len(ids))):
            raise ValueError(f"{self.model_id}: class IDs must be unique and contiguous from 0, got {ids}")
        if len(set(names)) != len(names) or len(set(stable)) != len(stable):
            raise ValueError(f"{self.model_id}: class names and stable IDs must be unique within the namespace")
        return self

    def class_map(self) -> dict[int, str]:
        return {c.class_id: c.class_name for c in self.classes}


class TaxonomyManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str
    taxonomy_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    status: Literal["draft-for-review", "approved"]
    notes: str
    models: list[ModelNamespace] = Field(min_length=1)
    output_record: dict

    @model_validator(mode="after")
    def supported_and_unique_models(self):
        if self.schema_version not in SUPPORTED_SCHEMAS:
            raise ValueError(f"unsupported taxonomy schema {self.schema_version!r}; supported: {sorted(SUPPORTED_SCHEMAS)}")
        ids = [m.model_id for m in self.models]
        if len(set(ids)) != len(ids):
            raise ValueError("model_id values must be unique")
        return self

    def model(self, model_id: str) -> ModelNamespace:
        for m in self.models:
            if m.model_id == model_id:
                return m
        raise TaxonomyError(f"unknown model_id {model_id!r}; known: {[m.model_id for m in self.models]}")


def load_manifest(path: Path = MANIFEST) -> TaxonomyManifest:
    path = Path(path)
    if not path.is_file():
        raise TaxonomyError(f"taxonomy manifest not found: {path}")
    try:
        return TaxonomyManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as exc:
        raise TaxonomyError(f"taxonomy manifest is not valid JSON: {exc}") from exc


# ---- authoritative sources ----------------------------------------------------------------
def names_from_data_yaml(path: Path) -> dict[int, str]:
    names = yaml.safe_load(Path(path).read_text(encoding="utf-8"))["names"]
    return dict(enumerate(names)) if isinstance(names, list) else {int(k): v for k, v in names.items()}


def names_from_python_constant(path: Path, constant: str):
    """Read a literal constant (e.g. NAMES, CLASSES) without importing heavy modules."""
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == constant for t in node.targets):
            value = ast.literal_eval(node.value)
            return dict(enumerate(value)) if isinstance(value, list) else {int(k): v for k, v in value.items()}
    raise TaxonomyError(f"{constant} not found in {path}")


def detector_sources() -> dict[str, dict[int, str]]:
    sources = {
        "Hazard_Expansion/configs/12class_data.yaml": names_from_data_yaml(ROOT / "Hazard_Expansion/configs/12class_data.yaml"),
        "ESE_CPU1_Quantization/common.py:NAMES": names_from_python_constant(ROOT / "ESE_CPU1_Quantization/common.py", "NAMES"),
        "EAP-2 baseline manifest": {int(k): v for k, v in json.loads(
            (ROOT / "EAP_2_CI_Model_Regression/baselines/cme-opt2-focal-cosine-12class-v1.json").read_text())["class_map"].items()},
    }
    metadata = ROOT / "Backend/weights/openvino_int8/metadata.yaml"
    if metadata.is_file():  # local export, not in Git
        sources["OpenVINO INT8 metadata.yaml"] = names_from_data_yaml(metadata)
    return sources


def cross_check(manifest: TaxonomyManifest) -> list[str]:
    """Return human-readable problems (empty list = consistent with the repository)."""
    problems: list[str] = []
    detector = manifest.model("industrix-detector")
    expected = detector.class_map()
    for source, names in detector_sources().items():
        if names != expected:
            problems.append(f"detector class map differs from {source}: manifest={expected} source={names}")
    thresholds = yaml.safe_load((ROOT / "Confidence_Calibration/configs/calibrated_thresholds.yaml").read_text(encoding="utf-8"))
    alert = {c.class_name for c in detector.classes if c.alert_class}
    if alert != set(thresholds["alert_classes"]):
        problems.append(f"alert classes {sorted(alert)} != calibrated alert_classes {sorted(thresholds['alert_classes'])}")
    for spec in detector.classes:
        configured = thresholds["classes"].get(spec.class_name, {}).get("confidence")
        if spec.alert_class and spec.confidence_threshold != configured:
            problems.append(f"{spec.class_name}: threshold {spec.confidence_threshold} != configured {configured}")
    severity = yaml.safe_load((ROOT / "SED_2_Alert_Escalation/configs/severity_rules.yaml").read_text(encoding="utf-8"))
    for spec in detector.classes:
        rule = severity["hazards"].get(spec.class_name)
        if spec.alert_class != (rule is not None):
            problems.append(f"{spec.class_name}: alert_class={spec.alert_class} but SED-2 rule {'exists' if rule else 'missing'}")
        if rule and isinstance(spec.severity, dict) and spec.severity.get("initial") != rule["initial_severity"]:
            problems.append(f"{spec.class_name}: severity initial {spec.severity.get('initial')} != SED-2 {rule['initial_severity']}")
    unknown = set(severity["hazards"]) - set(expected.values())
    if unknown:
        problems.append(f"SED-2 severity rules reference classes not in the taxonomy: {sorted(unknown)}")
    classifier = manifest.model("qci2-surface-classifier")
    qci2 = names_from_python_constant(ROOT / "QCI_2_Defect_Classifier/common.py", "CLASSES")
    if classifier.class_map() != qci2:
        problems.append(f"QCI-2 class map differs: manifest={classifier.class_map()} source={qci2}")
    return problems


def main() -> int:
    try:
        manifest = load_manifest()
    except (TaxonomyError, ValueError) as exc:
        print(f"TAXONOMY INVALID: {exc}")
        return 2
    problems = cross_check(manifest)
    for m in manifest.models:
        print(f"{m.model_id} ({m.model_version}): {len(m.classes)} classes "
              f"{', '.join(f'{c.class_id}={c.class_name}' for c in m.classes)}")
    for problem in problems:
        print(f"  CONFLICT: {problem}")
    print(f"taxonomy {manifest.taxonomy_version}: " + ("CONSISTENT" if not problems else f"{len(problems)} conflicts"))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
