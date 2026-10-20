"""EAP-3 container tests.

Static checks always run. Container checks need Docker plus the built images
(EAP3_IMAGE, default industrix:eap3 = bundled target; EAP3_RUNTIME_IMAGE, default
industrix:eap3-runtime). They skip with a reason when Docker/images are absent,
unless EAP3_REQUIRE_DOCKER=1, which turns a missing prerequisite into a failure.
"""
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pytest

TASK = Path(__file__).resolve().parents[1]
ROOT = TASK.parent
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
IMAGE = os.getenv("EAP3_IMAGE", "industrix:eap3")
RUNTIME_IMAGE = os.getenv("EAP3_RUNTIME_IMAGE", "industrix:eap3-runtime")
FIXTURE = ROOT / "tests" / "assets" / "ife_ui3_fire.png"
MODEL = ROOT / "Backend" / "best.pt"
LIMIT = 1_800_000_000
REQUIRE = os.getenv("EAP3_REQUIRE_DOCKER") == "1"


def _docker_ok():
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


def _image_exists(image):
    return subprocess.run(["docker", "image", "inspect", image], capture_output=True).returncode == 0


DOCKER = _docker_ok()
needs_image = pytest.mark.skipif(not REQUIRE and not (DOCKER and _image_exists(IMAGE)),
                                 reason=f"Docker daemon or image {IMAGE} unavailable; container checks NOT VERIFIED")
needs_runtime = pytest.mark.skipif(not REQUIRE and not (DOCKER and _image_exists(RUNTIME_IMAGE)),
                                   reason=f"Docker daemon or image {RUNTIME_IMAGE} unavailable")


def docker(*args, check=True, timeout=180):
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=check, timeout=timeout)


# ---- Static checks ---------------------------------------------------------------------
def test_dockerfile_is_multistage_with_slim_runtime():
    stages = re.findall(r"^FROM\s+(\S+)(?:\s+AS\s+(\S+))?", DOCKERFILE, re.M)
    assert [s[1] for s in stages] == ["builder", "runtime", "bundled"]
    runtime = DOCKERFILE.split("AS runtime", 1)[1].split("AS bundled", 1)[0]
    assert "build-essential" not in runtime and "gcc" not in runtime
    assert "COPY --from=builder /opt/venv /opt/venv" in runtime
    assert re.search(r"^USER industrix$", runtime, re.M)
    assert "ADD http" not in DOCKERFILE and "curl" not in DOCKERFILE and "wget" not in DOCKERFILE


def test_runtime_stage_does_not_copy_weights():
    runtime = DOCKERFILE.split("AS runtime", 1)[1].split("AS bundled", 1)[0]
    assert "best.pt" not in runtime.replace("INDUSTRIX_MODEL_PATH=/models/best.pt", "")
    assert "Backend/weights" not in runtime and "COPY Backend/ " not in runtime


def test_entrypoint_is_exec_form_on_exposed_port():
    cmd = json.loads(re.search(r"^CMD (\[.*\])$", DOCKERFILE, re.M).group(1))
    assert cmd[:2] == ["uvicorn", "Backend.main:api_app"] and cmd[cmd.index("--port") + 1] == "8000"
    assert re.search(r"^EXPOSE 8000$", DOCKERFILE, re.M) and "HEALTHCHECK" in DOCKERFILE


def test_offline_and_fail_fast_environment():
    for setting in ("YOLO_OFFLINE=true", "YOLO_AUTOINSTALL=false", "INDUSTRIX_REQUIRE_MODEL=1",
                    "INDUSTRIX_MODEL_PATH=/models/best.pt", "INFERENCE_ENGINE=pytorch"):
        assert setting in DOCKERFILE


def test_runtime_requirements_are_pinned_and_cpu_only():
    lines = [l.strip() for l in (TASK / "requirements-runtime.txt").read_text().splitlines()
             if l.strip() and not l.startswith("#") and not l.startswith("--")]
    assert lines and all("==" in l for l in lines), [l for l in lines if "==" not in l]
    names = {l.split("==")[0].lower() for l in lines}
    assert "opencv-python-headless" in names and "opencv-python" not in names
    assert {"torch", "torchvision", "ultralytics", "fastapi", "uvicorn"} <= names
    assert any(l.startswith("torch==") and l.endswith("+cpu") for l in lines)
    assert not names & {"jupyter", "pytest", "kagglehub", "albumentations", "mlflow"}


def test_dockerignore_excludes_non_runtime_content():
    ignore = (ROOT / ".dockerignore").read_text().splitlines()
    for entry in (".git", "**/runtime", "**/tests", "**/*.ipynb", "Hazard_Expansion", "final_dataset", ".env",
                  "Backend/weights/onnx_fp16", "**/venv"):
        assert entry in ignore, entry
    assert "!ESE_CPU1_Quantization/reports/artifact_manifest.json" in ignore


# ---- Built image -------------------------------------------------------------------------
@needs_image
def test_image_size_gate():
    # Unpacked filesystem (see check_image_size.py); .Size is compressed on the containerd store.
    raw = docker("run", "--rm", "--network", "none", "--user", "0", "--entrypoint", "du", IMAGE, "-sxb", "/").stdout.split()[0]
    assert int(raw) < LIMIT, f"{IMAGE} unpacked filesystem is {raw} bytes (>= {LIMIT})"


@needs_image
def test_image_runs_as_non_root_without_build_tools():
    out = docker("run", "--rm", "--entrypoint", "sh", IMAGE, "-c",
                 "id -u; for t in gcc cc g++ make apt-get pip; do command -v $t || echo no-$t; done").stdout.split()
    assert out[0] == "10001"
    assert {"no-gcc", "no-cc", "no-g++", "no-make"} <= set(out)


@needs_image
def test_image_contents_and_imports():
    script = ("import importlib,os,json;"
              "mods=['torch','torchvision','cv2','ultralytics','openvino','fastapi','uvicorn','reportlab','pypdf','lap'];"
              "[importlib.import_module(m) for m in mods];"
              "import Backend.main as m;"
              "paths=['/models/best.pt','/app/Backend/main.py','/app/ESE_CPU1_Quantization/reports/artifact_manifest.json',"
              "'/app/Backend/weights/openvino_int8/model.xml','/app/Confidence_Calibration/configs/calibrated_thresholds.yaml'];"
              "bad=[p for p in ['/app/.git','/app/Hazard_Expansion','/app/EAP_2_CI_Model_Regression','/app/Backend/weights/onnx_fp16'] if os.path.exists(p)];"
              "print(json.dumps(dict(missing=[p for p in paths if not os.path.exists(p)],unexpected=bad,"
              "tests=[r for r,d,f in os.walk('/app') if r.endswith('/tests')],"
              "notebooks=[f for r,d,fs in os.walk('/app') for f in fs if f.endswith('.ipynb')])))")
    result = json.loads(docker("run", "--rm", "--entrypoint", "python", IMAGE, "-c", script).stdout.strip().splitlines()[-1])
    assert result == dict(missing=[], unexpected=[], tests=[], notebooks=[])


class Container:
    def __init__(self, image, *extra, env=None):
        self.name = f"eap3-{uuid.uuid4().hex[:8]}"
        args = ["run", "-d", "--name", self.name, "-p", "127.0.0.1::8000"]
        for key, value in (env or {}).items():
            args += ["-e", f"{key}={value}"]
        docker(*args, *extra, image)

    @property
    def url(self):
        port = docker("port", self.name, "8000").stdout.strip().splitlines()[0].rsplit(":", 1)[1]
        return f"http://127.0.0.1:{port}"

    def wait_healthy(self, timeout=120):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(self.url + "/health", timeout=5) as response:
                    return json.loads(response.read())
            except (urllib.error.URLError, ConnectionError, IndexError, subprocess.CalledProcessError):
                if self.state()["Status"] == "exited":
                    raise AssertionError("container exited:\n" + self.logs())
                time.sleep(2)
        raise AssertionError("container did not become healthy:\n" + self.logs())

    def state(self):
        return json.loads(docker("inspect", self.name, "--format", "{{json .State}}").stdout)

    def logs(self):
        result = docker("logs", self.name, check=False)
        return result.stdout + result.stderr

    def remove(self):
        docker("rm", "-f", self.name, check=False)


def post_image(base, path, name="frame.png"):
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
            f"Content-Type: image/png\r\n\r\n").encode() + Path(path).read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(base + "/predict", data=body, method="POST",
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"{}")


@pytest.fixture(scope="module")
def running():
    container = Container(IMAGE)
    try:
        container.health = container.wait_healthy()
        yield container
    finally:
        container.remove()


@needs_image
def test_health_reports_real_verified_model(running):
    health = running.health
    assert health["model_loaded"] and health["classes"] == 12
    assert health["model_sha256"] == "c4aba081f6357e23a7370a5f7cf98eff2c6faa0c4c20a2d4dcb8bcabdd490061"
    logs = running.logs()
    assert "Loaded YOLO model from /models/best.pt" in logs and "Traceback" not in logs


@needs_image
def test_real_inference_contract_repeat_and_malformed(running, tmp_path):
    from EAP_2_CI_Model_Regression import gate
    from PIL import Image
    manifest = gate.load_manifest(ROOT / "EAP_2_CI_Model_Regression/baselines/cme-opt2-focal-cosine-12class-v1.json")
    status, payload = post_image(running.url, FIXTURE)
    assert status == 200, payload
    with Image.open(FIXTURE) as image:
        response = gate.validate_response(payload, manifest.class_map, *image.size)
    assert response.detections, "real model returned no detections on the fire fixture"
    for _ in range(3):
        assert post_image(running.url, FIXTURE) == (status, payload)
    bad = tmp_path / "corrupt.png"
    bad.write_bytes(b"\x89PNG not really")
    status, error = post_image(running.url, bad)
    assert status == 400 and "not a readable image" in error["detail"]


@needs_image
def test_memory_stable_over_repeated_requests(running):
    def usage():
        raw = docker("stats", "--no-stream", "--format", "{{.MemUsage}}", running.name).stdout.split("/")[0].strip()
        value, unit = re.match(r"([\d.]+)\s*([KMG]i?B)", raw).groups()
        return float(value) * {"KiB": 2**10, "MiB": 2**20, "GiB": 2**30, "KB": 1e3, "MB": 1e6, "GB": 1e9}[unit]
    for _ in range(3):
        post_image(running.url, FIXTURE)
    before = usage()
    for _ in range(30):
        assert post_image(running.url, FIXTURE)[0] == 200
    growth = (usage() - before) / before * 100
    print(f"container memory growth over 30 requests: {growth:+.2f}%")
    assert growth < 10, f"memory grew {growth:.2f}% over 30 warmed requests"


@needs_image
def test_offline_network_none_and_read_only_rootfs():
    name = f"eap3-off-{uuid.uuid4().hex[:8]}"
    probe = ("import sys,time,json,threading,urllib.request,uvicorn;"
             "from Backend.main import api_app;"
             "server=uvicorn.Server(uvicorn.Config(api_app,host='127.0.0.1',port=8000,log_level='warning'));"
             "threading.Thread(target=server.run,daemon=True).start();"
             "[time.sleep(1) for _ in range(90) if not server.started];"
             "data=open('/probe/fire.png','rb').read();b='x';"
             "body=(f'--{b}\\r\\nContent-Disposition: form-data; name=\"file\"; filename=\"f.png\"\\r\\nContent-Type: image/png\\r\\n\\r\\n').encode()+data+f'\\r\\n--{b}--\\r\\n'.encode();"
             "r=urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8000/predict',data=body,headers={'Content-Type':'multipart/form-data; boundary=x'}),timeout=60);"
             "out=json.loads(r.read());print(json.dumps(dict(status=r.status,detections=len(out['detections']))));server.should_exit=True")
    result = docker("run", "--rm", "--name", name, "--network", "none", "--read-only", "--tmpfs", "/tmp",
                    "--tmpfs", "/data:uid=10001,gid=10001",
                    "-v", f"{FIXTURE}:/probe/fire.png:ro", "--entrypoint", "python", IMAGE, "-c", probe, check=False, timeout=240)
    assert result.returncode == 0, result.stdout + result.stderr
    outcome = json.loads(result.stdout.strip().splitlines()[-1])
    assert outcome["status"] == 200 and outcome["detections"] > 0
    assert "QCI4_MONITOR_UNAVAILABLE" not in result.stderr, result.stderr  # shared DB is on writable /data
    assert "not writable" not in result.stdout + result.stderr


@needs_image
def test_clean_stop_on_sigterm():
    container = Container(IMAGE)
    try:
        container.wait_healthy()
        started = time.time()
        docker("stop", "--time", "30", container.name)
        elapsed = time.time() - started
        state = container.state()
        assert state["ExitCode"] == 0 and elapsed < 25, (state, elapsed)
        assert "Finished server process" in container.logs()
    finally:
        container.remove()


@needs_runtime
def test_runtime_image_fails_clearly_without_weights():
    result = docker("run", "--rm", RUNTIME_IMAGE, check=False, timeout=180)
    assert result.returncode != 0
    assert "No model checkpoint found" in result.stdout + result.stderr


@needs_runtime
@pytest.mark.skipif(not MODEL.is_file(), reason="Backend/best.pt not present (weights are not in Git); mount test NOT VERIFIED")
def test_runtime_image_with_mounted_weights_and_bad_checksum(tmp_path):
    container = Container(RUNTIME_IMAGE, "-v", f"{MODEL}:/models/best.pt:ro")
    try:
        assert container.wait_healthy()["model_loaded"]
    finally:
        container.remove()
    result = docker("run", "--rm", "-e", "INDUSTRIX_MODEL_SHA256=" + "0" * 64, "-v", f"{MODEL}:/models/best.pt:ro",
                    RUNTIME_IMAGE, check=False, timeout=180)
    assert result.returncode != 0 and "checksum mismatch" in result.stdout + result.stderr
    corrupt = tmp_path / "best.pt"
    corrupt.write_bytes(b"not a checkpoint")
    result = docker("run", "--rm", "-v", f"{corrupt}:/models/best.pt:ro", RUNTIME_IMAGE, check=False, timeout=180)
    assert result.returncode != 0 and "Failed to load model" in result.stdout + result.stderr
