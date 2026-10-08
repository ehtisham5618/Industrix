"""One continuous monitored process using the existing CPU2 capture manager."""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import platform
import threading
import time
import traceback
import tracemalloc
from datetime import datetime,timezone
from pathlib import Path

from ESE_CPU1_Quantization.common import ROOT,SOURCE_VERSION,digest,write_json
from .engine import OpenVINODetector

VERSION='ESECPU3-soak60-v1'
REPORTS=ROOT/'SED_3_Stress_Testing/reports'


def keep_awake(enable):
    """Temporary thread-scoped Windows sleep inhibition, restored in finally."""
    if platform.system()!='Windows':return None
    import ctypes
    flags=0x80000000 | (0x00000001 if enable else 0)
    if not ctypes.windll.kernel32.SetThreadExecutionState(flags):
        raise RuntimeError('Unable to set temporary Windows system-awake request')
    return 'SetThreadExecutionState ES_CONTINUOUS | ES_SYSTEM_REQUIRED'


def parse_args(argv=None):
    parser=argparse.ArgumentParser(description='Continuous CPU-only OpenVINO INT8 three-feed soak')
    parser.add_argument('--duration',type=float,default=3600)
    parser.add_argument('--engine',choices=['openvino'],default='openvino')
    parser.add_argument('--streams',type=int,choices=[3],default=3)
    parser.add_argument('--config',type=Path,default=ROOT/'SED_1_Multi_Camera/configs/3_cameras.json')
    parser.add_argument('--report',type=Path,default=REPORTS/'cpu_soak_report.json')
    parser.add_argument('--sample-interval',type=float,default=1)
    parser.add_argument('--warmup',type=float,default=60)
    args=parser.parse_args(argv)
    args.config=args.config.resolve()
    if (not all(math.isfinite(v) for v in (args.duration,args.sample_interval,args.warmup))
        or args.duration<=0 or args.sample_interval<=0 or args.warmup<0):
        parser.error('duration/sample-interval must be positive; warmup must be nonnegative')
    return args


def hardware():
    import cv2,psutil,openvino as ov
    import subprocess,sys
    cpu=platform.processor()
    if platform.system()=='Windows':
        try:
            probe=subprocess.run(['powershell','-NoProfile','-Command','(Get-CimInstance Win32_Processor).Name'],
                                 capture_output=True,text=True,timeout=10,check=True)
            cpu=probe.stdout.strip() or cpu
        except Exception:pass
    return dict(cpu=cpu,physical_cores=psutil.cpu_count(logical=False),logical_cores=psutil.cpu_count(),
        ram_bytes=psutil.virtual_memory().total,os=platform.platform(),python=sys.version,
        openvino=ov.__version__,opencv=cv2.__version__,psutil=psutil.__version__)


class FrameTimingManager:
    """Attach diagnostic routing timing to the existing manager without changing ingestion."""
    @staticmethod
    def create(cameras,detector,policy,escalation,path):
        from SED_1_Multi_Camera.scripts.stream_manager import MultiCameraStreamManager
        class MeasuredManager(MultiCameraStreamManager):
            def _route_result(self,packet,*args,**kwargs):
                began=time.perf_counter()
                super()._route_result(packet,*args,**kwargs)
                self.frame_writer.writerow(dict(elapsed_seconds=time.perf_counter()-detector.started_at,
                    camera_id=packet.camera_id,frame_id=packet.frame_id,
                    routing_ms=(time.perf_counter()-began)*1000,
                    end_to_end_ms=self.metrics[packet.camera_id].latencies[-1]*1000))
        manager=MeasuredManager(cameras,detector,alert_policy_factory=policy,escalation_manager=escalation)
        manager.frame_log=path.open('w',newline='',encoding='utf-8')
        manager.frame_writer=csv.DictWriter(manager.frame_log,
            fieldnames=['elapsed_seconds','camera_id','frame_id','routing_ms','end_to_end_ms'])
        manager.frame_writer.writeheader()
        return manager


def sample(manager,monitor,detector,started,warmup,previous):
    row=monitor.sample().to_dict()
    now=time.perf_counter();elapsed=now-started
    current,peak=tracemalloc.get_traced_memory()
    calls,recent=detector.snapshot()
    row=dict(timestamp=row['timestamp'],elapsed_seconds=elapsed,soak_elapsed_seconds=elapsed-warmup,
        warmup=elapsed<warmup,sample_interval_seconds=max(.000001,now-previous['time']),
        process_cpu_pct=row['process_cpu_percent'],normalized_process_cpu_pct=row['process_cpu_percent']/monitor.psutil.cpu_count(),
        system_cpu_pct=row['cpu_percent'],process_rss_mb=row['process_rss_mb'],system_ram_pct=row['system_memory_percent'],
        tracemalloc_current_mb=current/1048576,tracemalloc_peak_mb=peak/1048576,
        cpu_freq_mhz=row['cpu_freq_mhz'],cpu_freq_min_mhz=row['cpu_freq_min_mhz'],cpu_freq_max_mhz=row['cpu_freq_max_mhz'],
        cpu_temp_c=row['cpu_temp_c'],thermal_sensor_source=row['thermal_sensor_source'],
        thread_count=row['thread_count'],python_thread_count=threading.active_count(),
        capture_thread_count=sum(w.thread.is_alive() for w in manager.workers),
        scheduler_alive=manager.scheduler_thread.is_alive(),inference_calls=calls,
        inference_latency_mean_ms=sum(r[0] for r in recent)/len(recent) if recent else None,
        active_streams=sum(m.status=='running' and w.thread.is_alive()
                           for m,w in zip(manager.metrics.values(),manager.workers)),
        event_store_size=len(manager.escalation_manager.event_store.events),
        event_history_size=len(manager.escalation_manager.event_store.history),
        tracker_live_states=sum(len(p.manager.states) for p in manager.alert_policies.values()),
        errors=sum(m.worker_crashes for m in manager.metrics.values()),
        read_failures=sum(m.decode_failures for m in manager.metrics.values()),
        reconnects=sum(m.reconnections for m in manager.metrics.values()),
        buffer_overruns=sum(m.overload_drops for m in manager.metrics.values()))
    evaluated_delta=0
    for camera_id,m in manager.metrics.items():
        delta=m.processed-previous.get(camera_id,0);evaluated_delta+=delta
        row.update({camera_id+'_captured':m.captured,camera_id+'_evaluated':m.processed,
            camera_id+'_evaluated_delta':delta,camera_id+'_fps':delta/row['sample_interval_seconds'],
            camera_id+'_skips':m.configured_skips,camera_id+'_buffer_occupancy':manager.queues[camera_id].qsize(),
            camera_id+'_buffer_overruns':m.overload_drops,camera_id+'_read_failures':m.decode_failures,
            camera_id+'_loop_rewinds':m.loop_rewinds,camera_id+'_status':m.status})
    row['evaluated_delta']=evaluated_delta
    row['aggregate_fps']=evaluated_delta/row['sample_interval_seconds']
    return row,dict(time=now,**{c:m.processed for c,m in manager.metrics.items()})


def snapshot_delta(snapshot):
    latest=tracemalloc.take_snapshot()
    entries=[]
    for stat in latest.compare_to(snapshot,'lineno'):
        if stat.size_diff<=0:continue
        site=stat.traceback[0]
        try:name=Path(site.filename).relative_to(ROOT).as_posix()
        except ValueError:name=Path(site.filename).name
        entries.append(dict(file=name,line=site.lineno,size_delta_bytes=stat.size_diff,count_delta=stat.count_diff))
        if len(entries)==10:break
    return entries


def run(args):
    import cv2,torch
    from SED_1_Multi_Camera.scripts.config import load_camera_configs
    from SED_3_Stress_Testing.scripts.resource_monitor import ResourceMonitor
    from CME_OPT3_ByteTrack.pipeline import TrackAwarePolicy
    from Confidence_Calibration.scripts.alert_policy import load_policy_config
    from SED_2_Alert_Escalation.scripts.factory import create_default_escalation_manager
    from .report import summarize,render
    args.report=args.report.resolve();out=args.report.parent;out.mkdir(parents=True,exist_ok=True)
    prefix=args.report.stem.replace('_report','')
    paths={name:out/(prefix+suffix) for name,suffix in
           [('telemetry','_timeseries.csv'),('inference','_inference.csv'),('frames','_frames.csv'),('allocations','_allocation_deltas.json')]}
    cv2.setNumThreads(1);torch.set_num_threads(1)
    cameras=load_camera_configs(args.config)
    if len(cameras)!=3 or any(not Path(c.source).is_file() for c in cameras):
        raise RuntimeError('Soak requires exactly three available local CPU2 simulation files')
    sources={}
    for c in cameras:
        cap=cv2.VideoCapture(c.source)
        if not cap.isOpened():raise RuntimeError('Soak source cannot be opened: '+c.camera_id)
        sources[c.camera_id]=dict(name=c.name,path=Path(c.source).relative_to(ROOT).as_posix(),sha256=digest(c.source),
            encoded_fps=cap.get(cv2.CAP_PROP_FPS),width=cap.get(3),height=cap.get(4),loop=True)
        cap.release()
    host=hardware()
    detector=OpenVINODetector(timing_path=paths['inference'])
    cfg=load_policy_config(ROOT/'Confidence_Calibration/configs/calibrated_thresholds.yaml')
    event_log=ROOT/'SED_2_Alert_Escalation/runtime'/(prefix+'_alert_events.jsonl')
    if event_log.exists():
        event_log=event_log.with_name(prefix+'_alert_events_'+str(time.time_ns())+'.jsonl')
    escalation=create_default_escalation_manager(ROOT,log_path=event_log,history_limit=1024)
    manager=FrameTimingManager.create(cameras,detector,lambda:TrackAwarePolicy(cfg),escalation,paths['frames'])
    monitor=ResourceMonitor(enable_gpu=False,enable_cpu_sensors=True)
    if monitor.psutil is None:raise RuntimeError('Mandatory psutil monitoring unavailable')
    exceptions=[];status='incomplete';failure_reason=None;allocations=[]
    utc_start=datetime.now(timezone.utc).isoformat()
    threads_before=monitor.process.num_threads()
    awake_request=keep_awake(True)
    tracemalloc.start(1)
    started=time.perf_counter();detector.started_at=started;detector.warmup_seconds=args.warmup
    previous=dict(time=started);next_sample=started;deadline=started+args.warmup+args.duration
    snapshot=None;next_snapshot=args.warmup
    measurements_start=None;counts_at_start=None
    try:
        with paths['telemetry'].open('w',newline='',encoding='utf-8') as log:
            writer=None
            manager.start()
            while time.perf_counter()<deadline:
                now=time.perf_counter()
                if now>=next_sample:
                    row,previous=sample(manager,monitor,detector,started,args.warmup,previous)
                    if writer is None:
                        writer=csv.DictWriter(log,fieldnames=list(row));writer.writeheader()
                    writer.writerow(row);log.flush()
                    if measurements_start is None and not row['warmup']:
                        measurements_start=now
                        counts_at_start={c:m.processed for c,m in manager.metrics.items()}
                        snapshot=tracemalloc.take_snapshot()
                        next_snapshot=row['elapsed_seconds']+900
                    if snapshot is not None and row['elapsed_seconds']>=next_snapshot:
                        allocations.append(dict(soak_elapsed_seconds=row['soak_elapsed_seconds'],top_growth=snapshot_delta(snapshot)))
                        write_json(paths['allocations'],allocations);next_snapshot+=900
                    if row['elapsed_seconds']>=60 and int(row['elapsed_seconds'])%60<args.sample_interval+1:
                        print(f"elapsed={row['elapsed_seconds']:.1f}s soak={max(0,row['soak_elapsed_seconds']):.1f}s active={row['active_streams']} evaluated={sum(m.processed for m in manager.metrics.values())} RSS={row['process_rss_mb']:.1f}MiB python={row['tracemalloc_current_mb']:.1f}MiB overruns={row['buffer_overruns']}",flush=True)
                    if ((row['active_streams']!=3 and row['elapsed_seconds']>=10)
                        or not row['scheduler_alive'] or row['errors'] or monitor.exceptions):
                        raise RuntimeError('Mandatory stream, inference or telemetry worker failed: '+str(manager.scheduler_error or monitor.exceptions))
                    if row['sample_interval_seconds']>max(15,args.sample_interval*5):
                        raise RuntimeError('Telemetry gap exceeded continuity limit; suspend/stall cannot count as a monitored soak')
                    next_sample=now+args.sample_interval
                if manager.stop_event.wait(min(.1,max(0,next_sample-time.perf_counter()))):
                    raise RuntimeError('Stream stop event set before workload deadline')
            capture_elapsed=time.perf_counter()-started
            deadline_counts={c:m.processed for c,m in manager.metrics.items()}
            final,previous=sample(manager,monitor,detector,started,args.warmup,previous)
            if writer:writer.writerow(final);log.flush()
            status='completed'
    except (Exception,KeyboardInterrupt) as exc:
        capture_elapsed=time.perf_counter()-started
        deadline_counts={c:m.processed for c,m in manager.metrics.items()}
        failure_reason=str(exc);status='incomplete' if isinstance(exc,KeyboardInterrupt) else 'failed'
        exceptions.append(dict(timestamp=time.time(),elapsed_seconds=capture_elapsed,camera=None,component='soak_main',
            exception_class=type(exc).__name__,message=str(exc),traceback=traceback.format_exc()))
    finally:
        threads_pre_shutdown=monitor.process.num_threads()
        try:manager.stop(timeout=30)
        except Exception as exc:
            status='failed';failure_reason='Shutdown failed: '+str(exc)
            exceptions.append(dict(timestamp=time.time(),elapsed_seconds=time.perf_counter()-started,camera=None,
                component='shutdown',exception_class=type(exc).__name__,message=str(exc),traceback=traceback.format_exc()))
        if snapshot is not None:
            allocations.append(dict(soak_elapsed_seconds=capture_elapsed-args.warmup,top_growth=snapshot_delta(snapshot)))
        write_json(paths['allocations'],allocations)
        traced_end=tracemalloc.get_traced_memory();tracemalloc.stop()
        detector.close();manager.frame_log.flush();manager.frame_log.close()
        keep_awake(False)
    duration=max(0,capture_elapsed-args.warmup)
    context=dict(status=status,failure_reason=failure_reason,started_at_utc=utc_start,
        finished_at_utc=datetime.now(timezone.utc).isoformat(),duration_requested_seconds=args.duration,
        duration_actual_seconds=duration,capture_wall_seconds=capture_elapsed,
        wall_seconds_with_shutdown=time.perf_counter()-started,warmup_seconds=args.warmup,
        sample_interval_seconds=args.sample_interval,engine='openvino',model_version=SOURCE_VERSION,
        temporary_sleep_inhibition=awake_request,
        config_version=VERSION,ingestion_config_version='ESECPU2-async-ring15-sample4-v1',
        source_config=args.config.relative_to(ROOT).as_posix(),source_config_sha256=digest(args.config),
        hardware=host,engine_verification=detector.verification,sources=sources,
        counts_at_soak_start=counts_at_start or {},evaluated_at_deadline=deadline_counts,
        thread_counts=dict(before=threads_before,before_shutdown=threads_pre_shutdown,after_shutdown=monitor.process.num_threads()),
        threads_after_shutdown=[w.thread.name for w in manager.workers if w.thread.is_alive()],
        scheduler_after_shutdown=manager.scheduler_thread.is_alive(),sensor_warnings=monitor.sensor_warnings,
        exceptions=exceptions+detector.errors+
            [m.last_exception for m in manager.metrics.values() if m.last_exception]+
            ([manager.scheduler_exception] if manager.scheduler_exception else []),
        manager_metrics={c:dict(captured=m.captured,evaluated=m.processed,intentional_skips=m.configured_skips,
            selected=m.eligible,read_failures=m.decode_failures,reconnects=m.reconnections,loop_rewinds=m.loop_rewinds,
            worker_crashes=m.worker_crashes,inference_drops=m.inference_drops,status=m.status,
            ring=manager.queues[c].snapshot()) for c,m in manager.metrics.items()},
        event_store=dict(retention_limit=1024,retained_events=len(escalation.event_store.events),
            archived_events=escalation.event_store.archived_events,log_bytes=event_log.stat().st_size if event_log.exists() else 0),
        traced_end_bytes=traced_end,
        code_base_commit='79a1d8cff0a95f6b2d1e0014c36dd60a4752c018',
        code_file_hashes={name:digest(ROOT/name) for name in
            ('ESE_CPU3_Soak_Test/engine.py','ESE_CPU3_Soak_Test/soak.py','SED_1_Multi_Camera/scripts/stream_manager.py')},
        telemetry_path=paths['telemetry'].relative_to(ROOT).as_posix(),
        inference_path=paths['inference'].relative_to(ROOT).as_posix(),frame_timings_path=paths['frames'].relative_to(ROOT).as_posix())
    report=summarize(context,paths)
    write_json(args.report,report)
    render(report,args.report)
    print(json.dumps(dict(status=report['status'],dod=report['dod'],duration=duration,
                         throughput=report['throughput']),indent=2),flush=True)
    return report


def main(argv=None):
    report=run(parse_args(argv))
    return 0 if report['dod']['overall_pass'] else 2


if __name__=='__main__':raise SystemExit(main())
