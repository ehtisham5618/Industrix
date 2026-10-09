"""Reuse SED-3 hardware sampling and read QCI manifests/alarm tables without actuation."""
from collections import deque
from contextlib import closing
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time
import uuid
from Backend.incidents.repository import ROOT,local_storage_path
from SED_3_Stress_Testing.scripts.resource_monitor import ResourceMonitor
from .contracts import Resources,DatasetHealth,AlertHealth,Snapshot,EdgeStatus,CloudStatus,TelemetryPayload,EventPayload,utc
from .inference import get_tracker
from .spool import OverflowError

def resolved(value):
    p=Path(value);p=(ROOT/p if not p.is_absolute() else p).resolve()
    if not local_storage_path(p):raise ValueError('Local storage required')
    return p

class Collector:
    def __init__(self,config,spool,worker,tracker=None,clock=time.time):
        self.config=config;self.spool=spool;self.worker=worker;self.tracker=tracker or get_tracker();self.clock=clock
        self.tracker.configure_window(config.inference_window)
        self.monitor=ResourceMonitor(enable_gpu=False,enable_cpu_sensors=False)
        # Do not start the older monitor's unbounded sample-history thread.
        self.monitor.exceptions=deque(self.monitor.exceptions,maxlen=8)
        self.history=deque(maxlen=config.history_capacity);self.lock=threading.RLock();self.sample_lock=threading.Lock()
        self.latest=None;self.cpu_thread=None;self.alerts_path=resolved(config.alerts_database)
        self.manifest_path=resolved(config.dataset_manifest);self.manifest_cache=None;self.manifest_mtime=None
        self.next_routine=0;self.stop_event=threading.Event();self.thread=None;self.last_error=None;self.source_initialized=False

    def resources(self):
        result=Resources();sample=self.monitor.sample();p=self.monitor.process;ps=self.monitor.psutil
        result.cpu_percent=sample.cpu_percent;result.process_cpu_percent=sample.process_cpu_percent
        result.ram_percent=sample.system_memory_percent;result.process_rss_mb=sample.process_rss_mb
        result.process_threads=sample.thread_count
        if self.cpu_thread!=threading.get_ident():
            # psutil's initial nonblocking CPU percentages are not a measured interval.
            result.cpu_percent=None;result.process_cpu_percent=None;self.cpu_thread=threading.get_ident()
        try:
            if p and ps:
                memory=ps.virtual_memory();disk=ps.disk_usage(str(self.spool.path.parent))
                result.ram_used_mb=memory.used/2**20;result.disk_free_bytes=disk.free;result.disk_used_percent=disk.percent
                result.process_uptime_seconds=max(0,self.clock()-p.create_time())
                result.process_handles=p.num_handles() if hasattr(p,'num_handles') else p.num_fds()
        except (OSError,RuntimeError) as exc:result.errors=[type(exc).__name__]
        if self.monitor.exceptions:result.errors=(result.errors+['resource_sample_error'])[:8]
        return result

    def dataset(self):
        try:
            stat=self.manifest_path.stat()
            if stat.st_size>131072:raise ValueError('Manifest exceeds bound')
            if self.manifest_mtime!=stat.st_mtime_ns:
                data=json.loads(self.manifest_path.read_text(encoding='utf-8'))
                self.manifest_cache=DatasetHealth(status='MANIFEST_VALIDATED' if data.get('status')=='SUCCESS' else 'ERROR',version=data.get('version'),
                    last_error=None if data.get('status')=='SUCCESS' else 'manifest_not_successful')
                self.manifest_mtime=stat.st_mtime_ns
            return self.manifest_cache.model_copy(deep=True)
        except FileNotFoundError:return DatasetHealth(last_error='manifest_unavailable')
        except (OSError,ValueError,TypeError):return DatasetHealth(status='ERROR',last_error='manifest_invalid_or_unreadable')

    def alert_health(self):
        if not self.alerts_path.is_file():return AlertHealth(last_error='qci3_database_not_initialized')
        try:
            with closing(sqlite3.connect(self.alerts_path.as_uri()+'?mode=ro',uri=True,timeout=.05)) as db:
                tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if not {'qci3_events','qci3_outbox','qci3_audit'}<=tables:return AlertHealth(last_error='qci3_tables_not_initialized')
                tiers={r[0]:r[1] for r in db.execute("SELECT json_extract(status,'$.severity'),COUNT(*) FROM qci3_events WHERE resolved=0 GROUP BY 1")}
                deliveries={r[0]:r[1] for r in db.execute('SELECT state,COUNT(*) FROM qci3_outbox GROUP BY state')}
                last=db.execute("SELECT time FROM qci3_audit WHERE after_state='critical' AND before_state!=after_state ORDER BY id DESC LIMIT 1").fetchone()
                pending=deliveries.get('PENDING',0)+deliveries.get('IN_FLIGHT',0)
                failed=deliveries.get('FAILED',0);unknown=deliveries.get('DELIVERY_UNKNOWN',0)
                return AlertHealth(status='DEGRADED' if failed+unknown else 'HEALTHY',active_info=tiers.get('info',0),
                    active_warning=tiers.get('warning',0),active_critical=tiers.get('critical',0),
                    retained_events=db.execute('SELECT COUNT(*) FROM qci3_events').fetchone()[0],
                    retained_transitions=db.execute('SELECT COUNT(*) FROM qci3_audit WHERE before_state!=after_state').fetchone()[0],
                    webhook_acknowledged=deliveries.get('ACKNOWLEDGED',0),webhook_failed=failed,webhook_unknown=unknown,webhook_pending=pending,
                    last_critical_at=datetime.fromisoformat(last[0]) if last else None)
        except (OSError,sqlite3.Error,ValueError,TypeError):return AlertHealth(status='ERROR',last_error='qci3_database_unreadable')

    def collect_events(self):
        if not self.config.cloud_enabled or not self.config.allow_event_sync or not self.alerts_path.is_file():return
        cursor=int(self.spool.get_meta('alert_cursor','0'))
        # QCI-3 tables stay read-only. A QCI-4-owned one-row marker identifies the
        # source database across relocation and prevents silent audit-counter reuse.
        if not self.source_initialized:
            with closing(sqlite3.connect(self.alerts_path,timeout=.25)) as source_db:
                if not source_db.execute("SELECT 1 FROM sqlite_master WHERE name='qci3_audit'").fetchone():return
                source_db.execute('CREATE TABLE IF NOT EXISTS qci4_alarm_source(singleton INTEGER PRIMARY KEY CHECK(singleton=1),identity TEXT NOT NULL)')
                source_db.execute('INSERT OR IGNORE INTO qci4_alarm_source VALUES(1,?)',(str(uuid.uuid4()),));source_db.commit()
            self.source_initialized=True
        with closing(sqlite3.connect(self.alerts_path.as_uri()+'?mode=ro',uri=True,timeout=.05)) as source_db:
            marker=source_db.execute('SELECT identity FROM qci4_alarm_source WHERE singleton=1').fetchone()
            if marker is None:raise ValueError('Missing alarm source identity')
            source_id=marker[0]
        expected_source=self.spool.get_meta('alert_source_identity')
        if expected_source is not None and expected_source!=source_id:raise ValueError('Alarm source changed; reviewed cursor migration required')
        if expected_source is None:self.spool.set_meta('alert_source_identity',source_id)
        with closing(sqlite3.connect(self.alerts_path.as_uri()+'?mode=ro',uri=True,timeout=.05)) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='qci3_audit'").fetchone():return
            rows=db.execute('''SELECT id,substr(source,1,129),substr(event,1,129),time,before_state,after_state,substr(detail,1,8193)
                FROM qci3_audit WHERE id>? ORDER BY id LIMIT 32''',(cursor,)).fetchall()
            maximum=db.execute('SELECT COALESCE(MAX(id),0) FROM qci3_audit').fetchone()[0]
            if maximum<cursor:raise ValueError('Alarm audit counter regressed')
        batch=[]
        for row in rows:
            if self.stop_event.is_set():break
            sequence,source,event,timestamp,before,after,detail=row
            if sequence>cursor+1:
                self.last_error='qci3_audit_retention_gap';self.spool.log('SOURCE_RETENTION_GAP',cursor=cursor,next_available=sequence)
            if before==after:
                batch.append((None,None,sequence));cursor=sequence;continue
            data=json.loads(detail)
            if len(source)>128 or len(event)>128 or len(detail)>8192:raise ValueError('Alarm summary metadata exceeds bound')
            activation=hashlib.sha256((self.spool.device_id+'\0'+source_id+'\0'+source+'\0'+event).encode()).hexdigest()
            payload=EventPayload(observed_at=datetime.fromisoformat(timestamp),activation_key=activation,
                transition_sequence=sequence,state=after,severity=data['actions'] and ('critical' if after=='critical' else 'warning' if after=='warning' else 'info') or 'info',
                model_version=data['model_version'],policy_version=data['policy_version'])
            # Resolved state retains the incident tier, rather than inventing normality.
            if after=='resolved':
                payload.severity=before if before in ('info','warning','critical') else 'info'
            batch.append(('event:'+source_id+':'+str(sequence),payload,sequence));cursor=sequence
        if batch:self.spool.enqueue_batch(batch)

    def sample(self):
        with self.sample_lock:
            began=time.perf_counter();errors=[]
            resources=self.resources();dataset=self.dataset();inference=self.tracker.snapshot(self.config.stale_inference_seconds)
            alerts=self.alert_health()
            try:self.collect_events()
            except OverflowError:errors.append('spool_capacity_reached')
            except (OSError,sqlite3.Error,ValueError,KeyError,TypeError):errors.append('alarm_sync_collection_failed')
            if self.last_error:errors.append(self.last_error)
            cloud=self.worker.snapshot()
            stats=self.spool.stats()
            active=None if alerts.active_info is None else alerts.active_info+alerts.active_warning+alerts.active_critical
            local_error=inference.status=='ERROR' or alerts.status=='ERROR'
            degraded=resources.errors or inference.status in ('UNKNOWN','STALE','IDLE') or alerts.status in ('UNKNOWN','DEGRADED') or dataset.status!='MANIFEST_VALIDATED' or errors
            edge=EdgeStatus.ERROR if local_error else EdgeStatus.DEGRADED if degraded else EdgeStatus.OFFLINE_LOCAL_ONLY if cloud.status in (CloudStatus.OFFLINE,CloudStatus.DEGRADED) else EdgeStatus.HEALTHY
            snapshot=Snapshot(timestamp=utc(self.clock()),edge_status=edge,resources=resources,dataset=dataset,inference=inference,alerts=alerts,
                cloud=cloud,spool=stats,events_processed=inference.inference_count,active_alerts=active,
                collection_latency_ms=(time.perf_counter()-began)*1000,sampler_running=bool(self.thread and self.thread.is_alive()),
                sync_worker_running=bool(self.worker.thread and self.worker.thread.is_alive()),sample_interval_seconds=self.config.sample_interval_seconds,
                error_categories=errors[:8])
            snapshot.outbound_telemetry_permitted=self.config.cloud_enabled and self.config.allow_telemetry_sync
            snapshot.outbound_event_summaries_permitted=self.config.cloud_enabled and self.config.allow_event_sync
            if self.config.cloud_enabled and self.config.allow_telemetry_sync and self.clock()>=self.next_routine:
                payload=TelemetryPayload(observed_at=snapshot.timestamp,cpu_percent=resources.cpu_percent,ram_percent=resources.ram_percent,
                    process_rss_mb=resources.process_rss_mb,disk_used_percent=resources.disk_used_percent,inference_count=inference.inference_count,
                    inference_latency_ms=inference.latency_ms,active_alerts=active,edge_status=edge)
                try:self.spool.enqueue('telemetry:'+str(int(self.clock()*1000000)),payload)
                except OverflowError:snapshot.error_categories.append('routine_spool_capacity_reached')
                self.next_routine=self.clock()+self.config.telemetry_sync_interval_seconds
            snapshot.collection_latency_ms=(time.perf_counter()-began)*1000
            with self.lock:self.latest=snapshot;self.history.append(snapshot)
            self.spool.log('TELEMETRY_SAMPLE',cloud_status=cloud.status.value,queue_depth=stats.pending,latency_ms=snapshot.collection_latency_ms)
            return snapshot.model_copy(deep=True)

    def status(self):
        with self.lock:result=self.latest.model_copy(deep=True) if self.latest else None
        if result is None:result=self.sample()
        # Cloud delivery state can change between hardware samples; never report stale ONLINE.
        result.cloud=self.worker.snapshot();result.spool=self.spool.stats()
        if result.edge_status==EdgeStatus.HEALTHY and result.cloud.status in (CloudStatus.OFFLINE,CloudStatus.DEGRADED):result.edge_status=EdgeStatus.OFFLINE_LOCAL_ONLY
        if result.edge_status==EdgeStatus.OFFLINE_LOCAL_ONLY and result.cloud.status in (CloudStatus.ONLINE,CloudStatus.DISABLED):result.edge_status=EdgeStatus.HEALTHY
        result.sampler_running=bool(self.thread and self.thread.is_alive());result.sync_worker_running=bool(self.worker.thread and self.worker.thread.is_alive())
        return result

    def _run(self):
        while not self.stop_event.is_set():
            try:self.sample()
            except (OSError,RuntimeError,ValueError,sqlite3.Error):self.last_error='telemetry_sampler_error'
            self.stop_event.wait(self.config.sample_interval_seconds)

    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive():return
            self.cpu_thread=None
            self.stop_event.clear();self.thread=threading.Thread(target=self._run,name='qci4-telemetry-sampler',daemon=False);self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=3)
        if self.thread and self.thread.is_alive():raise RuntimeError('Telemetry sampler did not shut down')
