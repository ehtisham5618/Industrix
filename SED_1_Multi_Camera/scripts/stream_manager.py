from __future__ import annotations

import queue
import threading
import time
import traceback
import re
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

if __package__ in (None, ''):
    import sys
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
    from ESE_CPU2_Async_RTSP.benchmark import main
    if __name__ == '__main__':
        raise SystemExit(main())

from .camera_source import CameraSource, FileCameraSource
from .geofence import filter_detections_for_camera
from .models import CameraConfig, CameraMetrics, DetectionResult, FramePacket, StreamStatus
from .ring_buffer import FrameRingBuffer


DetectorCallable = Callable[[list[Any]], tuple[list[list[dict[str, Any]]], float]]


class StreamWorker:
    def __init__(
        self,
        config: CameraConfig,
        frame_queue: FrameRingBuffer,
        metrics: CameraMetrics,
        stop_event: threading.Event,
        source_factory: Callable[[CameraConfig], CameraSource] | None = None,
    ):
        self.config = config
        self.frame_queue = frame_queue
        self.metrics = metrics
        self.stop_event = stop_event
        if not isinstance(frame_queue,FrameRingBuffer):
            raise ValueError('Capture workers require a fixed 15-frame FrameRingBuffer')
        self.source_factory = source_factory or (lambda cfg: FileCameraSource(cfg.source, loop=cfg.loop,stop_event=stop_event))
        self.thread = threading.Thread(target=self._run, name=f"capture-{config.camera_id}", daemon=False)

    def start(self) -> None:
        self.thread.start()

    def join(self, timeout: float | None = None) -> None:
        self.thread.join(timeout=timeout)

    def _run(self) -> None:
        source = None
        frame_id = 0
        self.metrics.started_at = perf_counter()
        self.metrics.status = "starting"
        try:
            source = self.source_factory(self.config)
            connected = False
            backoff = .25
            generation = 0
            while not self.stop_event.is_set():
                if not connected:
                    try:
                        source.open()
                        connected = True
                        self.metrics.status = 'running'
                        if self.metrics.reconnect_attempts:
                            generation += 1
                            self.metrics.reconnections += 1
                    except Exception:
                        self.metrics.open_failures += 1
                        if not getattr(source,'is_live',False):
                            raise
                        self.metrics.status = 'reconnecting'
                        self.metrics.reconnect_attempts += 1
                        source.close()
                        self.stop_event.wait(backoff)
                        backoff = min(4,backoff*2)
                        continue
                self.metrics.read_attempts += 1
                try:
                    ok, frame = source.read()
                except Exception:
                    if not getattr(source,'is_live',False):
                        raise
                    ok,frame=False,None
                if not ok:
                    if self.stop_event.is_set():
                        break
                    self.metrics.decode_failures += 1
                    if getattr(source,'is_live',False):
                        self.metrics.status = 'reconnecting'
                        self.metrics.reconnect_attempts += 1
                        connected = False
                        source.close()
                        self.stop_event.wait(backoff)
                        backoff = min(4,backoff*2)
                        continue
                    self.metrics.status = "ended"
                    break
                now = perf_counter()
                self.metrics.captured += 1
                backoff = .25
                self.metrics.source_fps = float(getattr(source,'source_fps',0) or 0)
                self.metrics.loop_rewinds = getattr(source,'loop_rewinds',0)
                packet = FramePacket(
                    camera_id=self.config.camera_id,
                    frame_id=frame_id,
                    timestamp=time.time(),
                    frame=frame,
                    source_fps=float(getattr(source, "source_fps", 0.0) or 0.0),
                    capture_time=now,
                    session_id=generation+getattr(source, 'session_generation', 0),
                    buffer_write_time=perf_counter(),
                )
                selected,overrun,_ = self.frame_queue.write(packet)
                self.metrics.eligible += int(selected)
                self.metrics.configured_skips += int(not selected)
                self.metrics.overload_drops += int(overrun)
                self.metrics.submitted += 1
                self.metrics.queue_depth_samples.append(self.frame_queue.qsize())
                frame_id += 1
        except Exception as exc:
            self.metrics.status = "failed"
            self.metrics.worker_crashes += 1
            # Source errors can contain private stream URLs; expose only safe types.
            self.metrics.last_error = f'{type(exc).__name__}: source unavailable or capture failed'
            self.metrics.last_exception = dict(timestamp=time.time(),camera=self.config.camera_id,
                component='capture',exception_class=type(exc).__name__,message=self.metrics.last_error,
                traceback=re.sub(r'(?:rtsp[s]?|https?)://\S+','[redacted source]',traceback.format_exc()))
        finally:
            if source is not None:
                try:
                    source.close()
                except Exception:
                    self.metrics.worker_crashes += 1
                    self.metrics.status = 'failed'
                    self.metrics.last_error = 'Camera resource release failed'
            self.metrics.ended_at = perf_counter()
            if self.metrics.status in {"running",'reconnecting'}:
                self.metrics.status = "stopped"


class MultiCameraStreamManager:
    def __init__(
        self,
        cameras: list[CameraConfig],
        detector: Any,
        alert_policy_factory: Callable[[], Any] | None = None,
        escalation_manager: Any | None = None,
        queue_size: int = 15,
        micro_batch: bool = True,
        source_factory: Callable[[CameraConfig], CameraSource] | None = None,
        ring_capacity: int = 15,
        result_callback: Callable | None = None,
    ):
        if len({c.camera_id for c in cameras}) != len(cameras):
            raise ValueError('Camera identifiers must be unique')
        self.cameras = {camera.camera_id: camera for camera in cameras if camera.enabled}
        self.detector = detector
        self.result_callback = result_callback
        self.alert_policies = {
            camera_id: alert_policy_factory() if alert_policy_factory else None for camera_id in self.cameras
        }
        self.escalation_manager = escalation_manager
        if ring_capacity != 15 or any(c.sample_every != 4 for c in cameras):
            raise ValueError('ESE-CPU2 requires ring_capacity=15 and sample_every=4')
        # Legacy queue_size remains accepted for existing clients, but cannot
        # change the fixed ring capacity. Backend returns the effective value.
        self.queues = {camera_id: FrameRingBuffer(ring_capacity) for camera_id in self.cameras}
        self.metrics = {camera_id: CameraMetrics() for camera_id in self.cameras}
        self.latest_results: dict[str, DetectionResult] = {}
        self.active_alerts: list[dict[str, Any]] = []
        self.active_escalations: list[dict[str, Any]] = []
        self.micro_batch = micro_batch
        self.source_factory = source_factory
        self.stop_event = threading.Event()
        self.result_lock = threading.Lock()
        self.workers: list[StreamWorker] = []
        self.scheduler_error = None
        self.scheduler_exception = None
        self._fair_offset = 0
        self.scheduler_thread = threading.Thread(target=self._scheduler_loop, name="sed1-inference-scheduler", daemon=True)

    def start(self) -> None:
        if self.scheduler_thread.is_alive() or any(w.thread.is_alive() for w in self.workers):
            raise RuntimeError('A stream session is already running or shutting down')
        self.stop_event.clear()
        self.scheduler_error = None
        self.scheduler_exception = None
        self._fair_offset = 0
        self.metrics = {camera_id: CameraMetrics() for camera_id in self.cameras}
        self.queues = {camera_id: FrameRingBuffer() for camera_id in self.cameras}
        with self.result_lock:
            self.latest_results.clear()
            self.active_alerts.clear()
            self.active_escalations.clear()
        for policy in self.alert_policies.values():
            if hasattr(policy, 'reset'):
                policy.reset()
        self.workers = [
            StreamWorker(
                self.cameras[camera_id],
                self.queues[camera_id],
                self.metrics[camera_id],
                self.stop_event,
                source_factory=self.source_factory,
            )
            for camera_id in self.cameras
        ]
        for worker in self.workers:
            worker.start()
        self.scheduler_thread = threading.Thread(target=self._scheduler_loop, name="sed1-inference-scheduler", daemon=False)
        self.scheduler_thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self.stop_event.set()
        deadline = perf_counter()+timeout
        for worker in self.workers:
            worker.join(timeout=max(0,deadline-perf_counter()))
        if self.scheduler_thread.ident is not None:
            self.scheduler_thread.join(timeout=max(0,deadline-perf_counter()))
        if self.scheduler_thread.is_alive() or any(worker.thread.is_alive() for worker in self.workers):
            raise RuntimeError('Stream shutdown is still waiting for capture/inference; do not start a second session yet')
        if self.scheduler_error:
            # Capture may finish an in-flight read after scheduler failure.
            for camera_id,ring in self.queues.items():
                while not ring.empty():
                    try: ring.get_nowait(); self.metrics[camera_id].inference_drops += 1
                    except queue.Empty: break
        ended = perf_counter()
        for metric in self.metrics.values():
            if metric.ended_at is None:
                metric.ended_at = ended
            if metric.status in {"running", "starting",'reconnecting'}:
                metric.status = "stopped"
        for camera_id, policy in self.alert_policies.items():
            if hasattr(policy, 'reset'):
                policy.reset()
            if self.escalation_manager is not None and hasattr(self.escalation_manager, 'reset_camera'):
                self.escalation_manager.reset_camera(camera_id)

    def restart(self) -> None:
        self.stop()
        self.start()

    def statuses(self) -> list[StreamStatus]:
        statuses = []
        for camera_id, camera in self.cameras.items():
            metric = self.metrics[camera_id]
            statuses.append(
                StreamStatus(
                    camera_id=camera_id,
                    name=camera.name,
                    enabled=camera.enabled,
                    status=metric.status,
                    captured=metric.captured,
                    eligible=metric.eligible,
                    processed=metric.processed,
                    overload_drops=metric.overload_drops,
                    drop_rate_pct=metric.unexpected_drop_rate,
                    processed_fps=metric.processed_fps,
                    queue_depth=self.queues[camera_id].qsize(),
                    last_error=metric.last_error,
                    capture_fps=metric.captured/max(.000001,(metric.ended_at or perf_counter())-(metric.started_at or perf_counter())),
                    read_failures=metric.decode_failures,
                    buffer_overruns=metric.overload_drops,
                    intentional_skips=metric.configured_skips,
                    last_frame_age_ms=metric.frame_ages_ms[-1] if metric.frame_ages_ms else None,
                    connected=metric.status=='running',
                )
            )
        return statuses

    def _scheduler_loop(self) -> None:
        try:
            self._run_scheduler()
        except Exception as exc:
            self.scheduler_error = f'{type(exc).__name__}: shared inference/tracking failed'
            self.scheduler_exception = dict(timestamp=time.time(),camera=None,component='shared_inference_tracking',
                exception_class=type(exc).__name__,message=self.scheduler_error,
                traceback=re.sub(r'(?:rtsp[s]?|https?)://\S+','[redacted source]',traceback.format_exc()))
            self.stop_event.set()
            for camera_id,ring in self.queues.items():
                while not ring.empty():
                    try: ring.get_nowait(); self.metrics[camera_id].inference_drops += 1
                    except queue.Empty: break

    def _run_scheduler(self) -> None:
        while (not self.stop_event.is_set() or any(w.thread.is_alive() for w in self.workers)
               or any(not q.empty() for q in self.queues.values())):
            packets = self._next_fair_batch()
            if not packets:
                for camera_id, metric in self.metrics.items():
                    policy = self.alert_policies[camera_id]
                    if metric.status in {'ended', 'failed'} and hasattr(policy, 'camera_id') and policy.camera_id is not None:
                        policy.reset()
                        if self.escalation_manager:
                            self.escalation_manager.reset_camera(camera_id)
                time.sleep(0.005)
                continue
            frames = [packet.frame for packet in packets]
            started = perf_counter()
            for packet in packets:
                metric = self.metrics[packet.camera_id]
                # get_nowait selection occurred immediately before this batch.
                metric.frame_ages_ms.append((started-packet.capture_time)*1000)
                metric.capture_sample_ms.append((self._selection_times[packet.camera_id]-packet.capture_time)*1000)
                metric.sample_inference_ms.append((started-self._selection_times[packet.camera_id])*1000)
            try:
                detections_by_frame, inference_elapsed = self.detector.predict_batch(frames)
                if len(detections_by_frame) != len(packets):
                    raise RuntimeError('Detector returned a mismatched batch')
            except Exception:
                for packet in packets: self.metrics[packet.camera_id].inference_drops += 1
                raise
            total_elapsed = perf_counter() - started
            per_frame_inference = inference_elapsed / max(1, len(packets))
            for first,(packet, detections) in enumerate(zip(packets, detections_by_frame)):
                try:
                    self._route_result(packet, detections, per_frame_inference, total_elapsed / max(1, len(packets)))
                except Exception:
                    # This and the remaining already-consumed frames never
                    # completed tracking/routing; retain complete loss accounting.
                    for unprocessed in packets[first:]:
                        self.metrics[unprocessed.camera_id].inference_drops += 1
                    raise

    def _next_fair_batch(self) -> list[FramePacket]:
        packets: list[FramePacket] = []
        ids=list(self.cameras)
        self._selection_times={}
        for n in range(len(ids)):
            camera_id=ids[(self._fair_offset+n)%len(ids)]
            try:
                packets.append(self.queues[camera_id].get_nowait())
                self._selection_times[camera_id]=perf_counter()
            except queue.Empty:
                continue
            if not self.micro_batch:
                self._fair_offset=(self._fair_offset+n+1)%len(ids)
                break
        return packets

    def _route_result(
        self,
        packet: FramePacket,
        detections: list[dict[str, Any]],
        inference_time: float,
        processing_time: float,
    ) -> None:
        camera = self.cameras[packet.camera_id]
        raw_detections = [dict(d) for d in detections]
        geofenced, matches = filter_detections_for_camera(detections, camera, frame=packet.frame)
        policy = self.alert_policies.get(packet.camera_id)
        calibrated = geofenced
        alerts: list[dict[str, Any]] = []
        escalations: list[dict[str, Any]] = []
        if policy is not None:
            if hasattr(policy, 'process_camera'):
                if policy.session_id is not None and policy.session_id != packet.session_id and self.escalation_manager:
                    self.escalation_manager.reset_camera(packet.camera_id, timestamp=packet.timestamp)
                policy_result = policy.process_camera(detections, camera, packet.frame,
                    packet.frame_id, packet.timestamp, session_id=packet.session_id)
                detections = policy_result['detections']
                matches = policy_result['geofence_matches']
            else:
                policy_result = policy.process_frame(geofenced, frame_index=packet.frame_id, timestamp_sec=packet.timestamp)
            calibrated = policy_result.get("calibrated_detections", [])
            alerts = policy_result.get("alerts", [])
            for alert in alerts:
                alert["camera_id"] = packet.camera_id
                alert["camera_name"] = camera.name
        if self.escalation_manager is not None and policy is not None:
            active_violations = policy_result.get('confirmed_violations')
            if active_violations is None:
                active_violations = self._confirmed_violations(policy, calibrated)
            escalations = [
                event.to_dict()
                for event in self.escalation_manager.process_frame(
                    packet.camera_id,
                    active_violations,
                    timestamp=packet.timestamp,
                )
            ]
        latency = perf_counter() - packet.capture_time
        result = DetectionResult(
            camera_id=packet.camera_id,
            frame_id=packet.frame_id,
            timestamp=packet.timestamp,
            detections=detections,
            calibrated_detections=calibrated,
            alerts=alerts,
            escalations=escalations,
            geofence_matches=matches,
            inference_time=inference_time,
            processing_time=processing_time,
            end_to_end_latency=latency,
            raw_detections=raw_detections,
            result_ready_at=time.time(),
        )
        metric = self.metrics[packet.camera_id]
        metric.processed += 1
        metric.inference_times.append(inference_time)
        metric.processing_times.append(processing_time)
        metric.latencies.append(latency)
        metric.queue_depth_samples.append(self.queues[packet.camera_id].qsize())
        with self.result_lock:
            self.latest_results[packet.camera_id] = result
            self.active_alerts.extend(alerts)
            del self.active_alerts[:-4096]
            if self.escalation_manager is not None:
                self.active_escalations = self.escalation_manager.active_events()
        if self.result_callback is not None:
            self.result_callback(packet,result)

    @staticmethod
    def _confirmed_violations(policy: Any, calibrated: list[dict[str, Any]]) -> list[dict[str, Any]]:
        active = getattr(getattr(policy, "manager", None), "active", {})
        active_classes = {class_name for class_name, is_active in active.items() if is_active}
        if not active_classes:
            return []
        best_by_class: dict[str, dict[str, Any]] = {}
        for det in calibrated:
            class_name = str(det.get("class_name", det.get("class", ""))).strip().lower().replace("_", " ").replace("-", " ")
            if class_name not in active_classes:
                continue
            current = best_by_class.get(class_name)
            if current is None or float(det.get("confidence", 0.0)) > float(current.get("confidence", 0.0)):
                out = dict(det)
                out["source"] = "cme2_confirmed"
                best_by_class[class_name] = out
        return list(best_by_class.values())


def default_model_path(project_root: str | Path) -> Path:
    return Path(project_root) / "Backend" / "best.pt"


