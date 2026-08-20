import tempfile
import os
import logging
import asyncio
import time
import threading
from functools import wraps
import sys
from pathlib import Path
from typing import Optional
from dataclasses import asdict, replace

from fastapi import FastAPI, File, UploadFile, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from Backend.offline_policy import configure_local_runtime
configure_local_runtime()
from CME_OPT3_ByteTrack.pipeline import TrackAwarePolicy, DEFAULT_TRACKER, DEFAULT_PERSIST_FRAMES
CME2_SCRIPTS = PROJECT_ROOT / "Confidence_Calibration" / "scripts"
if CME2_SCRIPTS.exists() and str(CME2_SCRIPTS) not in sys.path:
    sys.path.append(str(CME2_SCRIPTS))

try:
    from alert_policy import AlertPolicy, load_policy_config
except Exception:  # pragma: no cover - backend can still serve raw detections
    AlertPolicy = None
    load_policy_config = None

try:
    from SED_1_Multi_Camera.scripts.config import load_camera_configs
    from SED_1_Multi_Camera.scripts.detector import SharedYOLODetector
    from SED_1_Multi_Camera.scripts.stream_manager import MultiCameraStreamManager
except Exception:  # pragma: no cover - optional SED-1 demo layer
    load_camera_configs = None
    SharedYOLODetector = None
    MultiCameraStreamManager = None

try:
    from SED_2_Alert_Escalation.scripts.factory import create_default_escalation_manager
except Exception:  # pragma: no cover - optional SED-2 demo layer
    create_default_escalation_manager = None

logger = logging.getLogger("uvicorn.error")

api_app = FastAPI(title="Textile Defect Detection API")

api_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Lazy model holder
MODEL = None
MODEL_PATH: Optional[Path] = None
ALERT_POLICY = None
ALERT_CONFIG_PATH = PROJECT_ROOT / "Confidence_Calibration" / "configs" / "calibrated_thresholds.yaml"
CAMERA_CONFIG_PATH = PROJECT_ROOT / os.getenv('CAMERA_CONFIG','SED_1_Multi_Camera/configs/3_cameras.json')
SED2_RUNTIME_LOG_PATH = PROJECT_ROOT / "SED_2_Alert_Escalation" / "runtime" / "alert_events.jsonl"
STREAM_MANAGER = None
ESCALATION_MANAGER = None
TRACK_POLICIES = {}
from Backend.live_console import DisplayHub, ConsoleTelemetry, privacy_status
DISPLAY_HUB = DisplayHub()
CONSOLE_TELEMETRY = ConsoleTelemetry()
from Backend.incidents.api import router as incident_router
from Backend.incidents.service import get_logger as get_incident_logger
api_app.include_router(incident_router)
from QCI_3_Severity_IoT.api import router as quality_alarm_router, shutdown as shutdown_quality_alarms
api_app.include_router(quality_alarm_router)
api_app.add_event_handler('shutdown', shutdown_quality_alarms)
from QCI_4_Edge_Telemetry.api import router as edge_router, startup as startup_edge_monitor, shutdown as shutdown_edge_monitor
api_app.include_router(edge_router)
api_app.add_event_handler('startup', startup_edge_monitor)
api_app.add_event_handler('shutdown', shutdown_edge_monitor)


def publish_result(packet,result):
    DISPLAY_HUB.publish(packet,result)
    try:
        if result.escalations and STREAM_MANAGER is not None:
            get_incident_logger().observe(packet,result,STREAM_MANAGER.cameras[packet.camera_id],
                engine=str(stream_engine_status()))
    except Exception as exc:
        logger.error('INCIDENT_LOG_FAILED error_type=%s',type(exc).__name__)

STREAM_CONTROL_LOCK = threading.Lock()


def serialized_stream_control(operation):
    """Only one UI session may create or retire the shared stream manager."""
    @wraps(operation)
    def controlled(*args,**kwargs):
        if not STREAM_CONTROL_LOCK.acquire(blocking=False):
            raise HTTPException(status_code=409,detail='Another stream start/stop is in progress. Wait for it to finish, then retry.')
        try:return operation(*args,**kwargs)
        finally:STREAM_CONTROL_LOCK.release()
    return controlled


def stream_engine_status():
    if STREAM_MANAGER is None or not STREAM_MANAGER.scheduler_thread.is_alive():
        return dict(name='Idle',precision=None,device=None,active=False)
    detector=STREAM_MANAGER.detector
    if hasattr(detector,'verification'):
        return dict(name='OpenVINO',precision='INT8',device='CPU',active=True,
                    version=detector.verification['openvino_version'],model_version='cme-opt2-focal-cosine-12class-v1')
    return dict(name='PyTorch',precision='FP32',device=str(getattr(detector,'device','cpu') or 'cpu'),active=True,
                model_version='cme-opt2-focal-cosine-12class-v1')


@api_app.get('/system/status')
def system_status():
    cameras=load_camera_configs(CAMERA_CONFIG_PATH) if load_camera_configs else []
    telemetry=CONSOLE_TELEMETRY.sample(STREAM_MANAGER)
    from ESE_CPU1_Quantization.common import NAMES
    return dict(server_time=time.time(),engine=stream_engine_status(),telemetry=telemetry,
                privacy=privacy_status(cameras),model_classes=NAMES,
                capabilities={'forklift_proximity':False,'chemical_class':'chemical hazard'},
                ui_version='IFEUI1-multistream-console-v1',ingestion_version='ESECPU2-async-ring15-sample4-v1')


@api_app.on_event('shutdown')
def shutdown_streams():
    if STREAM_MANAGER is not None:STREAM_MANAGER.stop(timeout=30)


MODEL_SHA256: Optional[str] = None


def find_model_path() -> Optional[Path]:
    configured = os.getenv("INDUSTRIX_MODEL_PATH")
    if configured:
        # An explicit path is authoritative; never fall back to another checkpoint.
        return Path(configured) if Path(configured).is_file() else None
    candidates = [Path("best.pt"), Path(__file__).parent / "best.pt"]
    for p in candidates:
        if p.exists():
            return p
    return None


def _model_required() -> bool:
    return os.getenv("INDUSTRIX_REQUIRE_MODEL", "0") == "1"


def _fail_startup(message: str, cause: Optional[BaseException] = None):
    # Uvicorn does not run shutdown handlers when startup fails; stop the QCI-4
    # monitor's non-daemon threads here so the process (and container) can exit.
    shutdown_edge_monitor()
    raise RuntimeError(message) from cause


def _sha256(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


@api_app.on_event("startup")
def load_model_on_startup():
    global MODEL, MODEL_PATH, ALERT_POLICY, MODEL_SHA256
    MODEL_PATH = find_model_path()
    if MODEL_PATH is None:
        message = f"No model checkpoint found (INDUSTRIX_MODEL_PATH={os.getenv('INDUSTRIX_MODEL_PATH', 'unset')})"
        if _model_required():
            _fail_startup(message + "; mount the verified best.pt or unset INDUSTRIX_REQUIRE_MODEL")
        logger.warning(message + "; /predict will return 503 until a model is placed.")
        return

    MODEL_SHA256 = _sha256(MODEL_PATH)
    expected = os.getenv("INDUSTRIX_MODEL_SHA256")
    if expected and expected.lower() != MODEL_SHA256:
        _fail_startup(f"Model checksum mismatch for {MODEL_PATH}: {MODEL_SHA256} != expected {expected}")

    try:
        # Import ultralytics only when model file exists
        from ultralytics import YOLO

        MODEL = YOLO(str(MODEL_PATH))
        logger.info(f"Loaded YOLO model from {MODEL_PATH} sha256={MODEL_SHA256}")
    except Exception as e:
        MODEL = None
        if _model_required():
            _fail_startup(f"Failed to load model {MODEL_PATH}: {type(e).__name__}: {e}", e)
        logger.warning(f"Failed to load ultralytics YOLO model: {e}")

    if AlertPolicy is not None and load_policy_config is not None:
        try:
            ALERT_POLICY = AlertPolicy(load_policy_config(ALERT_CONFIG_PATH))
            logger.info(f"Loaded alert policy from {ALERT_CONFIG_PATH}")
        except Exception as e:
            ALERT_POLICY = None
            logger.warning(f"Failed to load alert policy from {ALERT_CONFIG_PATH}: {e}")


@api_app.get("/health")
def health():
    """Liveness/readiness for containers: 200 only when the detector is loaded."""
    body = {"status": "ok" if MODEL is not None else "model_unavailable", "model_loaded": MODEL is not None,
            "model_path": str(MODEL_PATH) if MODEL_PATH else None, "model_sha256": MODEL_SHA256,
            "classes": len(MODEL.names) if MODEL is not None else None}
    if MODEL is None:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=503, content=body)
    return body


def _require_stream_manager():
    if STREAM_MANAGER is None:
        raise HTTPException(status_code=404, detail="Multi-camera streams are not running. Call POST /streams/start first.")
    return STREAM_MANAGER


@api_app.post("/predict")
async def predict(
    file: UploadFile = File(...),
    apply_alert_policy: bool = Query(False, description="Apply CME-2 confidence calibration and temporal alert policy."),
    frame_index: int = Query(0, description="Frame index for temporal confirmation when apply_alert_policy=true."),
    timestamp_sec: Optional[float] = Query(None, description="Frame timestamp for temporal confirmation."),
    camera_id: str = Query('upload', description='Stable camera identity for a sequential stream.'),
    reset_tracker: bool = Query(False, description='Begin a new camera stream session.'),
):
    """Accepts multipart/form-data with field name 'file'. Returns detections in x1,y1,x2,y2 pixel coordinates."""
    if MODEL is None:
        raise HTTPException(status_code=503, detail="Model not available on server. Place best.pt in the backend folder and ensure ultralytics is installed.")

    # Save uploaded file to a temp file
    suffix = Path(file.filename).suffix or ".jpg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        try:
            from PIL import Image, UnidentifiedImageError
            with Image.open(tmp_path) as image:
                image.verify()
        # ImportError: ultralytics' patched Image.open imports pi-heif after any failed open;
        # without that optional plugin the file is unreadable here too, so it is still a 400.
        except (UnidentifiedImageError, OSError, SyntaxError, ValueError, ImportError) as exc:
            raise HTTPException(status_code=400, detail="Uploaded file is not a readable image.") from exc
        results = MODEL.predict(source=str(tmp_path), verbose=False, conf=0.1 if apply_alert_policy else 0.25)
        res = results[0]
        api_detections = []
        if res.boxes is not None:
            for box, confidence, class_id in zip(
                res.boxes.xyxy.cpu().tolist(),
                res.boxes.conf.cpu().tolist(),
                res.boxes.cls.cpu().tolist(),
            ):
                class_id = int(class_id)
                api_detections.append({
                    "class_id": class_id,
                    "class_name": res.names.get(class_id, str(class_id)),
                    "confidence": float(confidence),
                    "coordinates": {
                        "x1": float(box[0]),
                        "y1": float(box[1]),
                        "x2": float(box[2]),
                        "y2": float(box[3]),
                    },
                })

        response = {"filename": file.filename, "detections": api_detections}
        if apply_alert_policy:
            if ALERT_POLICY is None:
                raise HTTPException(status_code=503, detail="Alert policy is not available. Check CME-2 configuration.")
            from SED_1_Multi_Camera.scripts.models import CameraConfig
            import time
            import cv2
            if len(TRACK_POLICIES) >= 64 and camera_id not in TRACK_POLICIES:
                raise HTTPException(status_code=429, detail='Camera session limit reached; reset an existing session.')
            if camera_id not in TRACK_POLICIES:
                TRACK_POLICIES[camera_id] = TrackAwarePolicy(load_policy_config(ALERT_CONFIG_PATH))
            policy = TRACK_POLICIES[camera_id]
            if reset_tracker:
                policy.reset()
            try:
                response['alert_policy'] = policy.process_camera(api_detections,
                    CameraConfig(camera_id, camera_id, 'upload'), cv2.imread(str(tmp_path)),
                    frame_index, time.time() if timestamp_sec is None else timestamp_sec)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            response['detections'] = response['alert_policy']['detections']
        return response
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass


@api_app.get("/cameras")
def list_cameras():
    if load_camera_configs is None:
        raise HTTPException(status_code=503, detail="SED-1 camera configuration loader is not available.")
    try:
        cameras = load_camera_configs(CAMERA_CONFIG_PATH)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    statuses = {status.camera_id: asdict(status) for status in STREAM_MANAGER.statuses()} if STREAM_MANAGER else {}
    return {
        "cameras": [
            {
                "camera_id": camera.camera_id,
                "name": camera.name,
                "source": str(Path(camera.source).relative_to(PROJECT_ROOT)) if Path(camera.source).is_relative_to(PROJECT_ROOT) else '[private live source]',
                "simulation": not camera.source.lower().startswith(('rtsp:','rtsps:','http:','https:')),
                "enabled": camera.enabled,
                "monitored_classes": sorted(camera.monitored_classes),
                "geofences": [
                    {
                        "id": geofence.id,
                        "enabled": geofence.enabled,
                        "classes": sorted(geofence.classes),
                        "polygon": geofence.polygon,
                    }
                    for geofence in camera.geofences
                ],
                "status": statuses.get(camera.camera_id),
            }
            for camera in cameras
        ]
    }


@api_app.post("/streams/start")
@serialized_stream_control
def start_streams(
    streams: int = Query(3, ge=1, le=4),
    queue_size: int = Query(15, ge=1, le=16, description='Legacy parameter; effective raw ring capacity is fixed at 15.'),
    imgsz: int = Query(640, ge=160, le=1280),
    device: Optional[str] = Query(None),
    persist_frames: int = Query(DEFAULT_PERSIST_FRAMES, ge=1),
    tracker: str = Query(str(DEFAULT_TRACKER)),
    evaluated_fps: float = Query(10.0, gt=0, description='Deprecated compatibility parameter. Every fourth raw frame is selected; actual throughput is reported.'),
    engine: str = Query(os.getenv('INFERENCE_ENGINE','pytorch'),pattern='^(openvino|pytorch)$'),
):
    global STREAM_MANAGER, ESCALATION_MANAGER
    if MODEL_PATH is None and engine=='pytorch':
        raise HTTPException(status_code=503, detail="Model checkpoint is not available.")
    if any(component is None for component in (load_camera_configs, SharedYOLODetector, MultiCameraStreamManager, AlertPolicy, load_policy_config)):
        raise HTTPException(status_code=503, detail="SED-1 stream dependencies are not available.")
    if STREAM_MANAGER is not None:
        try:STREAM_MANAGER.stop(timeout=25)
        except RuntimeError as exc:
            raise HTTPException(status_code=409,detail='Previous stream shutdown is still in progress. Retry after it finishes; a second session was not started.') from exc
    cameras = load_camera_configs(CAMERA_CONFIG_PATH, limit=streams)
    if engine=='openvino':
        if imgsz!=640 or device not in (None,'cpu','CPU'):
            raise HTTPException(status_code=400,detail='Selected OpenVINO INT8 artifact requires CPU and 640x640')
        try:
            import cv2,torch
            cv2.setNumThreads(1);torch.set_num_threads(1)
            from ESE_CPU3_Soak_Test.engine import OpenVINODetector
            detector=OpenVINODetector()
        except Exception as exc:
            raise HTTPException(status_code=503,detail='Selected OpenVINO INT8 engine could not be verified; no fallback was used') from exc
    else:
        detector = SharedYOLODetector(MODEL_PATH, device=device, imgsz=imgsz)
    DISPLAY_HUB.reset()
    CONSOLE_TELEMETRY.history.clear();CONSOLE_TELEMETRY.cached=None
    ESCALATION_MANAGER = (
        create_default_escalation_manager(PROJECT_ROOT, log_path=SED2_RUNTIME_LOG_PATH,history_limit=1024)
        if create_default_escalation_manager is not None
        else None
    )
    if ESCALATION_MANAGER is not None:
        try:ESCALATION_MANAGER.event_store.transition_callback=get_incident_logger().on_transition
        except Exception as exc:logger.error('INCIDENT_STORAGE_INIT_FAILED error_type=%s',type(exc).__name__)
    STREAM_MANAGER = MultiCameraStreamManager(
        cameras,
        detector,
        alert_policy_factory=lambda: TrackAwarePolicy(load_policy_config(ALERT_CONFIG_PATH), persist_frames, tracker),
        escalation_manager=ESCALATION_MANAGER,
        queue_size=queue_size,
        micro_batch=True,
        result_callback=publish_result,
    )
    STREAM_MANAGER.start()
    return {"status": "started", "streams": len(cameras), "queue_size": 15, "imgsz": imgsz,
            "sample_every": 4, "sampling_phase": 0,"engine":stream_engine_status()}


@api_app.post("/streams/stop")
@serialized_stream_control
def stop_streams():
    global STREAM_MANAGER
    manager = _require_stream_manager()
    try:manager.stop(timeout=25)
    except RuntimeError as exc:
        raise HTTPException(status_code=409,detail='Stream shutdown is still in progress. Retry Stop feeds; the current manager is retained until workers finish.') from exc
    STREAM_MANAGER = None
    DISPLAY_HUB.reset()
    return {"status": "stopped"}


@api_app.get("/cameras/{camera_id}/status")
def camera_status(camera_id: str):
    manager = _require_stream_manager()
    for status in manager.statuses():
        if status.camera_id == camera_id:
            return asdict(status)
    raise HTTPException(status_code=404, detail=f"Unknown camera: {camera_id}")


@api_app.get("/cameras/{camera_id}/latest")
def camera_latest(camera_id: str):
    manager = _require_stream_manager()
    result = manager.latest_results.get(camera_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No result is available for {camera_id} yet.")
    return asdict(result)


@api_app.websocket('/cameras/{camera_id}/live')
async def camera_live(websocket: WebSocket,camera_id: str):
    cameras={c.camera_id:c for c in load_camera_configs(CAMERA_CONFIG_PATH)}
    if camera_id not in cameras:
        await websocket.close(code=1008);return
    await websocket.accept()
    subscription=DISPLAY_HUB.subscribe(camera_id);event=subscription[1]
    last_key=None
    try:
        while True:
            event.clear()
            manager=STREAM_MANAGER
            status=next((asdict(s) for s in manager.statuses() if s.camera_id==camera_id),None) if manager else None
            with DISPLAY_HUB.lock:latest=DISPLAY_HUB.latest.get(camera_id)
            key=(latest[2],latest[1]['frame_id']) if latest else None
            if latest is not None and key!=last_key and status and status['status']=='running':
                encoded=await asyncio.to_thread(DISPLAY_HUB.encode,camera_id,cameras[camera_id],stream_engine_status())
                if encoded is not None:
                    data,payload=encoded
                    await websocket.send_bytes(data)
                    last_key=(payload['generation'],payload['frame_id'])
                    try:
                        ack=await asyncio.wait_for(websocket.receive_json(),timeout=5)
                        if ack.get('type')=='rendered' and ack.get('frame_id')==payload['frame_id']:
                            with DISPLAY_HUB.lock:
                                DISPLAY_HUB.last_delivery_stats.append(dict(camera_id=camera_id,frame_id=payload['frame_id'],
                                    generation=payload['generation'],timestamp=time.time(),
                                    delivery_ms=ack.get('delivery_ms'),frame_age_ms=ack.get('frame_age_ms'),
                                    browser_update_at=ack.get('browser_update_at'),encoding_ms=payload['encoding_ms']))
                    except asyncio.TimeoutError:
                        await websocket.close(code=1013);return
            else:
                await websocket.send_json(dict(type='camera_state',camera_id=camera_id,status=status or {'status':'stopped'}))
            try:await asyncio.wait_for(event.wait(),timeout=1)
            except asyncio.TimeoutError:pass
    except (WebSocketDisconnect,RuntimeError):
        pass
    finally:DISPLAY_HUB.unsubscribe(camera_id,subscription)


@api_app.get("/alerts")
def list_alerts(limit: int = Query(50, ge=1, le=500)):
    manager = _require_stream_manager()
    return {
        "cme2_alerts": manager.active_alerts[-limit:],
        "sed2_active_events": manager.active_escalations[-limit:],
    }


@api_app.get("/alerts/active")
def list_active_escalations():
    manager = _require_stream_manager()
    if manager.escalation_manager is None:
        raise HTTPException(status_code=503, detail="SED-2 escalation manager is not available.")
    return {
        "events": manager.escalation_manager.active_events(),
        "camera_overall_severity": manager.escalation_manager.camera_overall_severity(),
    }


@api_app.get("/alerts/{event_id}")
def get_alert_event(event_id: str):
    manager = _require_stream_manager()
    if manager.escalation_manager is None:
        raise HTTPException(status_code=503, detail="SED-2 escalation manager is not available.")
    for event in manager.escalation_manager.all_events():
        if event["event_id"] == event_id:
            return event
    raise HTTPException(status_code=404, detail=f"Unknown alert event: {event_id}")


@api_app.get("/iot/status")
def iot_status():
    if ESCALATION_MANAGER is None:
        raise HTTPException(status_code=404, detail="SED-2 escalation manager has not been started.")
    return ESCALATION_MANAGER.dispatcher.relay.status()


@api_app.post("/iot/mock-reset")
def iot_mock_reset():
    if ESCALATION_MANAGER is None:
        raise HTTPException(status_code=404, detail="SED-2 escalation manager has not been started.")
    ESCALATION_MANAGER.dispatcher.relay.reset()
    return ESCALATION_MANAGER.dispatcher.relay.status()


def main():
    import argparse
    parser = argparse.ArgumentParser(description='YOLO + calibrated ByteTRACK + track-aware SED-2 alerts')
    parser.add_argument('--source', help='Video path; without it, serve the existing FastAPI API')
    parser.add_argument('--tracker', default='bytetrack.yaml')
    parser.add_argument('--persist-frames', type=int, default=DEFAULT_PERSIST_FRAMES)
    parser.add_argument('--device', default=None)
    parser.add_argument('--conf', type=float, default=0.1, help='Detector floor; per-class calibrated thresholds still apply')
    parser.add_argument('--output', default='CME_OPT3_ByteTrack/runtime/backend_video.jsonl')
    parser.add_argument('--evaluated-fps', type=float, default=10)
    parser.add_argument('--debug-tracker', action='store_true')
    args = parser.parse_args()
    if args.source:
        from CME_OPT3_ByteTrack.video_cli import run_video
        run_video(args, PROJECT_ROOT)
    else:
        import uvicorn
        uvicorn.run(api_app, host='127.0.0.1', port=8000)


if __name__ == '__main__':
    main()
