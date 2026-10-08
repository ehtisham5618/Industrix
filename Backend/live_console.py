"""Latest-only display transport and existing SED-3 hardware telemetry."""
from __future__ import annotations

import asyncio
import json
import struct
import threading
import time
from collections import deque
from dataclasses import asdict
from urllib.parse import urlparse
from pathlib import Path


class DisplayHub:
    def __init__(self):
        self.lock=threading.Lock()
        self.latest={}
        self.subscribers={}
        self.generation=0
        self.last_delivery_stats=deque(maxlen=600)

    def reset(self):
        with self.lock:
            self.latest.clear();self.generation+=1
            listeners=[entry for group in self.subscribers.values() for entry in group]
        for loop,event in listeners:
            if not loop.is_closed():loop.call_soon_threadsafe(event.set)

    def publish(self,packet,result):
        with self.lock:
            self.latest[packet.camera_id]=(packet.frame,asdict(result),self.generation)
            listeners=list(self.subscribers.get(packet.camera_id,[]))
        for loop,event in listeners:
            if not loop.is_closed():loop.call_soon_threadsafe(event.set)

    def subscribe(self,camera_id):
        entry=(asyncio.get_running_loop(),asyncio.Event())
        with self.lock:self.subscribers.setdefault(camera_id,[]).append(entry)
        return entry

    def unsubscribe(self,camera_id,entry):
        with self.lock:
            if entry in self.subscribers.get(camera_id,[]):self.subscribers[camera_id].remove(entry)

    def encode(self,camera_id,camera,engine):
        import cv2
        with self.lock:cached=self.latest.get(camera_id)
        if cached is None:return None
        frame,result,generation=cached
        h,w=frame.shape[:2];began=time.perf_counter()
        if w>960:
            display=cv2.resize(frame,(960,round(h*960/w)),interpolation=cv2.INTER_AREA)
        else:display=frame
        ok,jpeg=cv2.imencode('.jpg',display,[cv2.IMWRITE_JPEG_QUALITY,80])
        if not ok:raise RuntimeError('Unable to encode current camera frame')
        def key(d):
            coordinates=d.get('coordinates',{})
            return (d.get('class_id'),tuple(round(float(coordinates.get(k,0)),3) for k in ('x1','y1','x2','y2')))
        tracked={key(d):d for d in result['detections']}
        detections=[]
        for det in result['raw_detections']:
            if camera.monitored_classes and det['class_name'] not in camera.monitored_classes:continue
            detections.append({**det,**tracked.get(key(det),{}),
                'confirmation_status':tracked.get(key(det),{}).get('confirmation_status','detected')})
        payload={**result,'detections':detections,'camera_name':camera.name,'generation':generation,
            'frame_width':w,'frame_height':h,'display_width':display.shape[1],'display_height':display.shape[0],
            'coordinates_format':'xyxy_pixels_in_source_frame',
            'geofences':[asdict(g) for g in camera.geofences],
            'encoding_ms':(time.perf_counter()-began)*1000,'engine':engine,
            'simulation':not urlparse(camera.source).scheme.lower() in ('rtsp','rtsps','http','https'),
            'sent_at':time.time()}
        # JSON metadata is prefixed by its network-order byte count, then JPEG.
        metadata=json.dumps(payload,default=lambda v:sorted(v) if isinstance(v,set) else str(v),allow_nan=False).encode()
        return struct.pack('!I',len(metadata))+metadata+jpeg.tobytes(),payload


class ConsoleTelemetry:
    def __init__(self):
        from SED_3_Stress_Testing.scripts.resource_monitor import ResourceMonitor
        self.monitor=ResourceMonitor(enable_gpu=False)
        self.lock=threading.Lock();self.cached=None;self.last_sample=0
        self.history=deque(maxlen=60)

    def sample(self,manager):
        with self.lock:
            now=time.perf_counter()
            if self.cached is None or now-self.last_sample>=1:
                self.cached=self.monitor.sample().to_dict();self.last_sample=now
                counts={c:m.processed for c,m in manager.metrics.items()} if manager else {}
                self.history.append((now,counts))
            current=self.history[-1] if self.history else (now,{})
            earlier=next((r for r in self.history if current[0]-r[0]<=5),current)
            fps={c:max(0,(n-earlier[1].get(c,n))/max(.001,current[0]-earlier[0])) for c,n in current[1].items()}
            if manager:
                fps={c:f if manager.metrics[c].status=='running' else 0 for c,f in fps.items()}
            else:fps={}
            inference={}
            if manager and hasattr(manager.detector,'snapshot'):
                _,recent=manager.detector.snapshot()
                values=[float(row[0]) for row in recent]
                if values:
                    import statistics
                    inference=dict(model_inference_mean_ms=statistics.mean(values),
                        model_inference_p95_ms=statistics.quantiles(values,n=100,method='inclusive')[94] if len(values)>1 else values[0],
                        model_inference_samples=len(values),model_inference_metric='Pure OpenVINO infer request; latest 128 calls, excludes preprocess/NMS')
            return dict(timestamp=self.cached['timestamp'],cpu_system_percent=self.cached['cpu_percent'],
                cpu_process_percent=self.cached['process_cpu_percent'],process_rss_mb=self.cached['process_rss_mb'],
                memory_units='MiB; process RSS',cpu_metric='System CPU utilization',
                aggregate_evaluated_fps=sum(fps.values()),camera_evaluated_fps=fps,
                fps_metric='Completed evaluated frames/sec over the latest five-second window',
                sample_interval_seconds=1,**inference)


def privacy_status(cameras):
    import os
    from Backend.incidents.repository import ROOT,local_storage_path
    external=[v.strip() for v in os.getenv('RUNTIME_EXTERNAL_SERVICES','').split(',') if v.strip()]
    deployment=os.getenv('DEPLOYMENT_MODE','local')
    local_sources=all(not urlparse(c.source).scheme.lower() in ('rtsp','rtsps','http','https') for c in cameras)
    storage_local=all(local_storage_path(os.getenv(key,default)) for key,default in
        [('INCIDENT_DATABASE','Backend/data/events.db'),('INCIDENT_SNAPSHOTS','data/snapshots')])
    local=deployment=='local' and local_sources and storage_local and not external
    return dict(local_processing_verified=local,cloud_dependency_percent=0 if local else None,
        external_services=external,mode=deployment,
        basis='Local file sources, local CPU inference, local monitor, local SQLite/snapshots/ReportLab, local JSONL alert storage and software-only IoT' if local else
              'External source/service or deployment mode requires operator verification')
