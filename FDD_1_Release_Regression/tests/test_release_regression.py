"""FDD-1 gap-filling regression tests (API edge cases, startup, dashboard, schema compatibility).

Real-model tests need Backend/best.pt and skip with a reason when it is absent.
"""
import asyncio
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "Backend" / "best.pt"
FIRE = ROOT / "tests" / "assets" / "ife_ui3_fire.png"
TEXTILE = ROOT / "tests" / "assets" / "ife_ui3_textile.png"
needs_model = pytest.mark.skipif(not MODEL.is_file(), reason="Backend/best.pt not available (weights are not in Git)")


def call(method, path, model, **kwargs):
    """Drive the real FastAPI app in-process with an injected model (as EAP-2 does)."""
    import httpx
    import Backend.main as main
    previous = main.MODEL
    main.MODEL = model
    try:
        async def go():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.api_app), base_url="http://test") as client:
                return await client.request(method, path, **kwargs)
        return asyncio.run(go())
    finally:
        main.MODEL = previous


@pytest.fixture(scope="module")
def model():
    if not MODEL.is_file():
        pytest.skip("Backend/best.pt not available")
    from ultralytics import YOLO
    return YOLO(str(MODEL))


# ---- API contract and error handling ---------------------------------------------------
@needs_model
@pytest.mark.parametrize("files,status", [
    (None, 422),                                                    # missing multipart field
    ({"image": ("f.png", b"x", "image/png")}, 422),                 # wrong field name
    ({"file": ("empty.png", b"", "image/png")}, 400),               # empty upload
    ({"file": ("notes.txt", b"plain text, not an image", "text/plain")}, 400),  # unsupported content
    ({"file": ("bad.jpg", b"\xff\xd8\xff garbage", "image/jpeg")}, 400),         # corrupted JPEG header
])
def test_predict_rejects_invalid_input_with_documented_status(model, files, status):
    response = call("POST", "/predict", model, files=files) if files else call("POST", "/predict", model)
    assert response.status_code == status, response.text
    assert "Traceback" not in response.text and "c4aba081" not in response.text  # no internals leaked


def test_predict_and_health_report_503_without_model():
    import Backend.main as main
    response = call("POST", "/predict", None, files={"file": ("f.png", FIRE.read_bytes(), "image/png")})
    assert response.status_code == 503 and "Model not available" in response.json()["detail"]
    saved = main.MODEL
    try:
        main.MODEL = None
        from fastapi.testclient import TestClient
        assert TestClient(main.api_app).get("/health").status_code == 503
    finally:
        main.MODEL = saved


@needs_model
def test_requests_are_isolated_and_repeatable(model):
    first = call("POST", "/predict", model, files={"file": ("a.png", FIRE.read_bytes(), "image/png")}).json()
    other = call("POST", "/predict", model, files={"file": ("b.png", TEXTILE.read_bytes(), "image/png")}).json()
    again = call("POST", "/predict", model, files={"file": ("a.png", FIRE.read_bytes(), "image/png")}).json()
    assert first == again and first["filename"] == "a.png" and other["filename"] == "b.png"
    assert first["detections"] != other["detections"]


@needs_model
def test_dashboard_reads_exactly_the_fields_predict_returns(model):
    """Frontend/app.py consumes detections[].class_name/class_id/confidence/coordinates.x1..y2."""
    payload = call("POST", "/predict", model, files={"file": ("a.png", FIRE.read_bytes(), "image/png")}).json()
    source = (ROOT / "Frontend" / "app.py").read_text(encoding="utf-8")
    for key in ("detections", "coordinates", "class_name", "class_id", "x1", "y1", "x2", "y2"):
        assert f'"{key}"' in source, key
    assert payload["detections"], "fixture should produce detections"
    for det in payload["detections"]:
        assert {"class_id", "class_name", "confidence", "coordinates"} <= set(det)
        assert set(det["coordinates"]) == {"x1", "y1", "x2", "y2"}


# ---- Startup / configuration ------------------------------------------------------------
def test_fail_fast_startup_without_model(monkeypatch, tmp_path):
    import Backend.main as main
    monkeypatch.setenv("INDUSTRIX_REQUIRE_MODEL", "1")
    monkeypatch.setenv("INDUSTRIX_MODEL_PATH", str(tmp_path / "missing.pt"))
    with pytest.raises(RuntimeError, match="No model checkpoint found"):
        main.load_model_on_startup()


@needs_model
def test_checksum_mismatch_refuses_to_start(monkeypatch):
    import Backend.main as main
    monkeypatch.setenv("INDUSTRIX_REQUIRE_MODEL", "1")
    monkeypatch.setenv("INDUSTRIX_MODEL_PATH", str(MODEL))
    monkeypatch.setenv("INDUSTRIX_MODEL_SHA256", "0" * 64)
    saved = (main.MODEL, main.MODEL_PATH, main.MODEL_SHA256)
    try:
        with pytest.raises(RuntimeError, match="checksum mismatch"):
            main.load_model_on_startup()
    finally:
        main.MODEL, main.MODEL_PATH, main.MODEL_SHA256 = saved


def test_optional_model_startup_degrades_to_503_not_crash(monkeypatch, tmp_path):
    import Backend.main as main
    monkeypatch.delenv("INDUSTRIX_REQUIRE_MODEL", raising=False)
    monkeypatch.setenv("INDUSTRIX_MODEL_PATH", str(tmp_path / "missing.pt"))
    saved = (main.MODEL, main.MODEL_PATH)
    try:
        main.load_model_on_startup()
        assert main.MODEL_PATH is None
    finally:
        main.MODEL, main.MODEL_PATH = saved


# ---- Dashboard ----------------------------------------------------------------------------
def test_dashboard_renders_without_uncaught_exception_when_backend_down(monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("BACKEND_URL", "http://127.0.0.1:9")  # nothing listens here
    app = AppTest.from_file(str(ROOT / "Frontend" / "app.py"), default_timeout=60).run()
    assert not app.exception, [e.value for e in app.exception]
    assert app.title[0].value == "Industrial Vision Console"
    assert [t.label for t in app.tabs] == ["Live Monitor", "Image Inference"]


@pytest.mark.skipif(not os.getenv("FDD1_BACKEND_URL"), reason="set FDD1_BACKEND_URL to render against a live backend")
def test_dashboard_renders_against_live_backend(monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("BACKEND_URL", os.environ["FDD1_BACKEND_URL"])
    app = AppTest.from_file(str(ROOT / "Frontend" / "app.py"), default_timeout=60).run()
    assert not app.exception, [e.value for e in app.exception]
    errors = [e.value for e in app.error]
    assert not any("unavailable" in e.lower() for e in errors), errors


# ---- Offline ---------------------------------------------------------------------------------
def test_runtime_entry_points_have_no_cloud_inference_clients():
    import ast
    banned = {"openai", "anthropic", "boto3", "google", "azure", "replicate", "roboflow", "inference_sdk", "modal"}
    for rel in ("Backend/main.py", "Backend/live_console.py", "Backend/offline_policy.py", "Frontend/app.py",
                "Frontend/api_client.py", "EAP_5_Watchdog/supervisor.py"):
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        imported |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        assert not imported & banned, (rel, imported & banned)
    policy = (ROOT / "Backend/offline_policy.py").read_text(encoding="utf-8")
    assert "YOLO_OFFLINE" in policy and "YOLO_AUTOINSTALL" in policy
