"""EAP-2 tests. Unit/negative-control tests run anywhere (CI); real-model tests
need Backend/best.pt and skip with an explicit reason unless EAP2_REQUIRE_MODEL=1,
in which case a missing artifact is a failure."""
import ast
import json
import math
import os
import socket
from pathlib import Path

import pytest
from pydantic import ValidationError

from EAP_2_CI_Model_Regression import gate, runner

TASK = Path(__file__).resolve().parents[1]
ROOT = TASK.parent
MODEL = ROOT / "Backend" / "best.pt"
REQUIRE = os.getenv("EAP2_REQUIRE_MODEL") == "1"
needs_model = pytest.mark.skipif(not MODEL.is_file() and not REQUIRE,
                                 reason="Backend/best.pt not available (weights are not in Git); model tests NOT_VERIFIED")


@pytest.fixture(scope="module")
def manifest():
    return gate.load_manifest(runner.MANIFEST)


@pytest.fixture(scope="module")
def policy():
    data = json.loads(runner.POLICY.read_text())
    return gate.ThresholdPolicy.model_validate({k: data[k] for k in ("version", "thresholds")})


def detection(**overrides):
    item = dict(class_id=8, class_name="fire", confidence=0.9, coordinates=dict(x1=1, y1=2, x2=30, y2=40))
    item.update(overrides)
    return item


# ---- Manifest and class map -------------------------------------------------------------
def test_committed_baseline_is_valid_and_has_exact_class_map(manifest):
    assert manifest.class_map == {0: "baekra", 1: "color issues", 2: "contamination", 3: "cut", 4: "gray stitch",
                                  5: "selvet", 6: "stain", 7: "chemical hazard", 8: "fire", 9: "no helmet",
                                  10: "smoke", 11: "water leak"}
    assert "chemical leak" not in manifest.class_map.values()  # only classes present in the checkpoint
    assert manifest.dataset_counts["images"] == 334 and manifest.evaluation.conf == 0.001
    assert set(manifest.per_class_ap50) == set(manifest.class_map.values())


def test_manifest_rejects_invalid_values(manifest):
    data = manifest.model_dump()
    for path, value in ((("metrics", "map50"), 1.5), (("metrics", "recall"), float("nan")),
                        (("artifact_sha256",), "abc"), (("class_map",), {0: "a", 2: "b"})):
        broken = json.loads(json.dumps(data, default=str))
        target = broken
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        with pytest.raises(ValidationError):
            gate.BaselineManifest.model_validate(broken)


def test_missing_baseline_is_not_verified_not_pass(tmp_path):
    with pytest.raises(gate.RegressionError, match="NOT_VERIFIED"):
        gate.load_manifest(tmp_path / "none.json")


def test_class_map_change_detected(manifest):
    assert gate.compare_class_map(dict(manifest.class_map), manifest).status == "PASS"
    swapped = dict(manifest.class_map)
    swapped[7], swapped[11] = swapped[11], swapped[7]
    check = gate.compare_class_map(swapped, manifest)
    assert check.status == "FAIL" and "water leak" in check.detail
    assert gate.compare_class_map({**manifest.class_map, 12: "chemical leak"}, manifest).status == "FAIL"


def test_artifact_hash_mismatch_and_missing(tmp_path, manifest):
    fake = tmp_path / "best.pt"
    fake.write_bytes(b"corrupted checkpoint")
    assert gate.verify_artifact(fake, manifest).status == "FAIL"
    assert gate.verify_artifact(tmp_path / "absent.pt", manifest).status == "NOT_VERIFIED"


# ---- Output contract ---------------------------------------------------------------------
def test_valid_predict_payload_and_empty_detections(manifest):
    assert gate.validate_response(dict(filename="a.png", detections=[detection()]), manifest.class_map, 100, 100)
    assert gate.validate_response(dict(filename="a.png", detections=[]), manifest.class_map, 100, 100).detections == []


@pytest.mark.parametrize("bad", [dict(confidence=float("nan")), dict(confidence=1.2), dict(confidence=float("inf")),
                                 dict(class_id=-1), dict(class_name=""), dict(coordinates=dict(x1=5, y1=5, x2=4, y2=9)),
                                 dict(coordinates=dict(x1=0, y1=0, x2=float("nan"), y2=9)), dict(extra_field=1),
                                 dict(coordinates=dict(x1=0, y1=0, x2=10))])
def test_invalid_detection_rejected(manifest, bad):
    with pytest.raises(ValidationError):
        gate.validate_response(dict(filename="a", detections=[detection(**bad)]), manifest.class_map, 100, 100)


def test_class_name_mismatch_and_out_of_bounds_rejected(manifest):
    with pytest.raises(ValueError, match="class map"):
        gate.validate_response(dict(filename="a", detections=[detection(class_name="water leak")]), manifest.class_map, 100, 100)
    with pytest.raises(ValueError, match="bounds"):
        gate.validate_response(dict(filename="a", detections=[detection(coordinates=dict(x1=1, y1=1, x2=500, y2=9))]),
                               manifest.class_map, 100, 100)


# ---- Quality gate negative controls ------------------------------------------------------
def candidate_from(manifest, **changes):
    values = manifest.metrics.model_dump()
    values["per_class_ap50"] = dict(manifest.per_class_ap50)
    values.update(changes)
    return values


def test_unchanged_candidate_has_zero_delta_and_no_false_pass(manifest, policy):
    checks, regressions, metrics = gate.compare_metrics(candidate_from(manifest), manifest, policy,
                                                        manifest.evaluation.model_dump(), manifest.dataset_fingerprint)
    assert all(v == 0 for v in metrics["delta_pp"].values())
    assert not any(c.status == "FAIL" for c in checks)
    # tolerances are undefined, so the gate must not claim PASS for them
    assert any(c.status == "UNDEFINED_THRESHOLD" and "max_drop_pp" in c.name for c in checks)
    # the accepted model violates the CME-OPT2 chemical target; it is recorded, not hidden
    assert any(r["metric"] == "per_class:chemical hazard" for r in regressions)


def test_enforced_threshold_violation_fails(manifest):
    strict = gate.ThresholdPolicy(version="t", thresholds=[gate.Threshold(metric="map50", kind="max_drop_pp", value=1.0,
                                                                          enforce=True, source="negative control")])
    ok, _, _ = gate.compare_metrics(candidate_from(manifest, map50=manifest.metrics.map50 - 0.005), manifest, strict,
                                    manifest.evaluation.model_dump(), manifest.dataset_fingerprint)
    bad, regressions, _ = gate.compare_metrics(candidate_from(manifest, map50=manifest.metrics.map50 - 0.02), manifest, strict,
                                               manifest.evaluation.model_dump(), manifest.dataset_fingerprint)
    assert ok[0].status == "PASS" and bad[0].status == "FAIL"
    assert math.isclose(regressions[0]["delta_pp"], -2.0, abs_tol=1e-6)  # percentage points, not relative %


def test_missing_or_invalid_metric_rejected(manifest, policy):
    with pytest.raises(ValidationError):
        gate.compare_metrics(candidate_from(manifest, map50=None), manifest, policy, manifest.evaluation.model_dump(),
                             manifest.dataset_fingerprint)
    values = candidate_from(manifest)
    del values["per_class_ap50"]["smoke"]
    checks, _, _ = gate.compare_metrics(values, manifest, policy, manifest.evaluation.model_dump(), manifest.dataset_fingerprint)
    assert any(c.name == "quality_per_class_coverage" and c.status == "FAIL" for c in checks)


def test_dataset_or_settings_mismatch_not_comparable(manifest, policy):
    checks, _, _ = gate.compare_metrics(candidate_from(manifest), manifest, policy, manifest.evaluation.model_dump(), "0" * 64)
    assert checks[0].status == "FAIL" and "fingerprint" in checks[0].detail
    settings = manifest.evaluation.model_dump() | dict(imgsz=320)
    checks, _, _ = gate.compare_metrics(candidate_from(manifest), manifest, policy, settings, manifest.dataset_fingerprint)
    assert checks[0].status == "FAIL" and "settings" in checks[0].detail


def test_overall_status_never_promotes_not_verified():
    assert gate.overall(["PASS", "NOT_VERIFIED"]) == "NOT_VERIFIED"
    assert gate.overall(["PASS", "UNDEFINED_THRESHOLD"]) == "UNDEFINED_THRESHOLD"
    assert gate.overall(["NOT_VERIFIED", "FAIL"]) == "FAIL"
    assert gate.overall(["PASS"]) == "PASS"


def test_report_written_atomically(tmp_path):
    report = gate.RegressionReport(status="NOT_VERIFIED", code_status="PASS", model_release_status="NOT_VERIFIED",
                                   checks=[gate.Check(name="x", category="code", status="PASS", detail="d")])
    target = tmp_path / "r.json"
    gate.write_report(report, target)
    assert json.loads(target.read_text())["model_sha256"] is None and not list(tmp_path.glob("*.tmp"))


def test_dataset_fingerprint_detects_label_change(tmp_path):
    for split in ("test",):
        (tmp_path / "images" / split).mkdir(parents=True)
        (tmp_path / "labels" / split).mkdir(parents=True)
    (tmp_path / "images/test/a.jpg").write_bytes(b"img")
    (tmp_path / "labels/test/a.txt").write_text("0 0.5 0.5 0.1 0.1\n")
    first = runner.dataset_fingerprint(tmp_path, "test")
    (tmp_path / "labels/test/a.txt").write_text("1 0.5 0.5 0.1 0.1\n")
    assert runner.dataset_fingerprint(tmp_path, "test") != first
    (tmp_path / "images" / "val").mkdir()
    with pytest.raises(gate.RegressionError):
        runner.dataset_fingerprint(tmp_path, "val")


def test_golden_manifest_is_annotation_based(manifest):
    golden = json.loads(runner.GOLDEN.read_text())
    assert golden["reference_sha256"] == manifest.artifact_sha256
    assert {f["class_id"] for f in golden["fixtures"]} == set(manifest.class_map)
    assert "human annotation" in golden["expected_source"]


def test_eap2_modules_have_no_network_clients():
    banned = {"requests", "urllib", "boto3", "mlflow", "kagglehub", "modal"}
    for module in ("gate.py", "runner.py", "build_baseline.py"):
        tree = ast.parse((TASK / module).read_text(encoding="utf-8"))
        imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        imported |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        assert not imported & banned, module


def test_ci_workflow_runs_gate_tests_without_hiding_failures():
    workflow = (ROOT / ".github" / "workflows" / "model-regression.yml").read_text(encoding="utf-8")
    assert "continue-on-error" not in workflow
    assert "EAP_2_CI_Model_Regression/tests" in workflow and "validate_registry.py" in workflow


# ---- Real model (artifact present) ---------------------------------------------------------
@needs_model
def test_real_model_hash_class_map_and_predict_contract(manifest, monkeypatch):
    assert gate.verify_artifact(MODEL, manifest).status == "PASS"
    from ultralytics import YOLO
    model = YOLO(str(MODEL))
    assert gate.compare_class_map(model.names, manifest).status == "PASS"

    original = socket.socket.connect
    attempts = []

    def guard(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            attempts.append(address)
            raise AssertionError(f"non-loopback network access attempted: {address}")
        return original(self, address)  # asyncio's Windows self-pipe uses loopback
    monkeypatch.setattr(socket.socket, "connect", guard)
    payload = runner.predict_via_api(model, runner.FIXTURE)
    from PIL import Image
    with Image.open(runner.FIXTURE) as image:
        response = gate.validate_response(payload, manifest.class_map, *image.size)
    assert response.filename == runner.FIXTURE.name
    assert payload == runner.predict_via_api(model, runner.FIXTURE)
    assert attempts == []


@needs_model
def test_real_api_rejects_corrupt_image_without_crash(tmp_path):
    # Defect found by EAP-2 (unhandled ValueError -> HTTP 500); fixed in EAP-3 with a 400.
    from ultralytics import YOLO
    bad = tmp_path / "corrupt.png"
    bad.write_bytes(b"\x89PNG not really")
    with pytest.raises(gate.RegressionError, match="/predict returned 400"):
        runner.predict_via_api(YOLO(str(MODEL)), bad)


def test_missing_model_gives_not_verified_report(tmp_path):
    report = runner.run(tmp_path / "missing.pt", tmp_path / "no_dataset", True, tmp_path / "report.json")
    assert report.status == "NOT_VERIFIED" and report.code_status == "PASS"
    assert report.model_sha256 is None and report.model_id is None
    assert {c.name: c.status for c in report.checks}["artifact_hash"] == "NOT_VERIFIED"
