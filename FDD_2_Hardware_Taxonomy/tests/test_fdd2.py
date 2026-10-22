"""FDD-2 validation: taxonomy manifest vs repository artifacts, schema negative cases,
documentation completeness, and the hardware-probe output contract."""
import copy
import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from FDD_2_Hardware_Taxonomy import taxonomy as tx

ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / "docs" / "deployment" / "HARDWARE_SIZING_GUIDE.md"
SPEC = ROOT / "docs" / "specifications" / "HAZARD_TAXONOMY.md"
RAW = json.loads(tx.MANIFEST.read_text(encoding="utf-8"))


def manifest_with(mutate):
    data = copy.deepcopy(RAW)
    mutate(data)
    return data


# ---- taxonomy vs repository ----------------------------------------------------------------
def test_manifest_parses_and_matches_every_authoritative_source():
    manifest = tx.load_manifest()
    assert tx.cross_check(manifest) == []


def test_detector_namespace_is_exactly_the_model_classes():
    detector = tx.load_manifest().model("industrix-detector")
    yaml_names = tx.names_from_data_yaml(ROOT / "Hazard_Expansion/configs/12class_data.yaml")
    assert detector.class_map() == yaml_names and len(yaml_names) == 12
    assert "chemical hazard" in yaml_names.values() and "chemical leak" not in yaml_names.values()


def test_namespaces_are_independent():
    m = tx.load_manifest()
    detector, classifier = m.model("industrix-detector"), m.model("qci2-surface-classifier")
    assert detector.class_map()[0] != classifier.class_map()[0]  # ID 0 means different things per model
    assert classifier.class_map() == tx.names_from_python_constant(ROOT / "QCI_2_Defect_Classifier/common.py", "CLASSES")


def test_alert_thresholds_and_severity_are_references_not_inventions():
    detector = tx.load_manifest().model("industrix-detector")
    for spec in detector.classes:
        if spec.domain == "textile_defect":
            assert spec.severity == "not configured" and not spec.alert_class
        else:
            assert isinstance(spec.confidence_threshold, float) and spec.severity["policy"] == "SED2-alert-escalation-v1"


def test_every_class_is_documented_in_the_markdown_spec():
    text = SPEC.read_text(encoding="utf-8")
    for model in tx.load_manifest().models:
        for spec in model.classes:
            assert f"`{spec.class_name}`" in text, spec.class_name
    assert tx.load_manifest().taxonomy_version in text


# ---- schema negative cases ---------------------------------------------------------------------
@pytest.mark.parametrize("mutate,match", [
    (lambda d: d["models"][0]["classes"][1].update(class_id=0), "unique and contiguous"),
    (lambda d: d["models"][0]["classes"][1].update(class_name="baekra"), "unique"),
    (lambda d: d["models"][0]["classes"].pop(), None),  # removing a class must break the source cross-check
    (lambda d: d["models"][0]["classes"][0].pop("definition"), "definition"),
    (lambda d: d["models"][0]["classes"][0].update(definition="short"), "at least 20"),
    (lambda d: d.update(schema_version="v999"), "unsupported taxonomy schema"),
    (lambda d: d.update(taxonomy_version="one"), "taxonomy_version"),
    (lambda d: d["models"].append(copy.deepcopy(d["models"][0])), "model_id values must be unique"),
    (lambda d: d["models"][0]["classes"][0].update(domain="weather"), "domain"),
])
def test_malformed_manifests_are_rejected(mutate, match):
    data = manifest_with(mutate)
    if match is None:
        problems = tx.cross_check(tx.TaxonomyManifest.model_validate(data))
        assert problems and "differs" in problems[0]
    else:
        with pytest.raises(ValidationError, match=match):
            tx.TaxonomyManifest.model_validate(data)


def test_renamed_class_and_unknown_model_fail_clearly(tmp_path):
    renamed = tx.TaxonomyManifest.model_validate(manifest_with(
        lambda d: d["models"][0]["classes"][7].update(class_name="chemical leak")))
    problems = tx.cross_check(renamed)
    assert any("differs" in p for p in problems) and any("SED-2" in p or "alert classes" in p for p in problems)
    with pytest.raises(tx.TaxonomyError, match="unknown model_id"):
        tx.load_manifest().model("other-model")
    bad = tmp_path / "bad.json"
    bad.write_text("{oops", encoding="utf-8")
    with pytest.raises(tx.TaxonomyError, match="not valid JSON"):
        tx.load_manifest(bad)
    with pytest.raises(tx.TaxonomyError, match="not found"):
        tx.load_manifest(tmp_path / "missing.json")


def test_threshold_drift_is_detected():
    drifted = tx.TaxonomyManifest.model_validate(manifest_with(
        lambda d: d["models"][0]["classes"][10].update(confidence_threshold=0.25)))  # smoke is 0.50 in config
    assert any("smoke: threshold" in p for p in tx.cross_check(drifted))


# ---- documentation completeness ------------------------------------------------------------------
def test_hardware_guide_has_required_sections_and_labels():
    text = GUIDE.read_text(encoding="utf-8")
    for heading in ("What actually runs", "Measured evidence", "Sizing methodology", "Deployment profiles",
                    "Compatibility and prerequisites", "Benchmark procedure", "Decision process",
                    "Open acceptance criteria", "Glossary", "Change history"):
        assert heading in text, heading
    for label in ("Measured", "Estimate", "Not yet benchmarked", "Tested", "not tested"):
        assert label.lower() in text.lower(), label
    assert "production-approved" in text


def test_guide_artifact_facts_match_the_repository():
    text = GUIDE.read_text(encoding="utf-8")
    model = ROOT / "Backend/best.pt"
    if model.is_file():
        assert f"{model.stat().st_size:,}" in text
    assert "c4aba081" in text and "640" in text
    referenced = re.findall(r"`((?:reports|SED_3_Stress_Testing|ESE_CPU3_Soak_Test|Hazard_Expansion|Backend)/[^`\s]+\.(?:json|md|yaml|py))`", text)
    missing = [p for p in referenced if not (any(ROOT.glob(p)) if "*" in p else (ROOT / p).exists())]
    assert not missing, missing


# ---- hardware probe contract -------------------------------------------------------------------------
PROBES = sorted((ROOT / "reports" / "fdd2").glob("hardware_probe_*.json"))


@pytest.mark.skipif(not PROBES, reason="no hardware probe output recorded yet")
@pytest.mark.parametrize("path", PROBES, ids=lambda p: p.stem)
def test_probe_output_reports_real_host_workload_and_method(path):
    report = json.loads(path.read_text(encoding="utf-8"))
    host = report["host"]
    for key in ("platform", "physical_cores", "logical_cores", "total_ram_bytes", "python"):
        assert host[key], key
    assert report["artifacts"]["pytorch_fp32"]["sha256"] in (None, "c4aba081f6357e23a7370a5f7cf98eff2c6faa0c4c20a2d4dcb8bcabdd490061")
    for result in report["results"]:
        if result["measured"]:
            lat = result["latency_ms"]
            assert result["iterations"] >= 30 and result["warmup"] >= 1
            assert 0 < lat["min"] <= lat["p50"] <= lat["p95"] <= lat["max"]
            assert result["peak_rss_during_inference_bytes"] >= result["rss_after_load_bytes"] > 0
            assert "batch 1" in result["latency_definition"]
        else:
            assert result["reason"]


def test_probe_records_unavailable_backend_without_inventing_numbers(monkeypatch):
    from FDD_2_Hardware_Taxonomy import hardware_probe as hp

    def broken():
        raise FileNotFoundError("export missing")
    result = hp.measure("openvino_int8", broken, iterations=5, warmup=1)
    assert result == dict(backend="openvino_int8", measured=False, reason="FileNotFoundError: export missing")
