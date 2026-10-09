"""Actual local classifier/alerts through outage, and measured failover-cycle RSS."""
from __future__ import annotations
from collections import deque
from contextlib import closing
from datetime import datetime,timezone
import argparse
import csv
import hashlib
import json
from pathlib import Path
import psutil
import sqlite3
import statistics
import subprocess
import threading
import time
import uuid
from .contracts import Config,CloudStatus
from .api import EdgeService
from .inference import InferenceTracker
from .mock_cloud import MockCloud
from QCI_3_Severity_IoT.offline import loopback_only
from QCI_3_Severity_IoT.engine import AlarmEngine
from QCI_3_Severity_IoT.contracts import Config as AlarmConfig,Rule,Event,Resolve

ROOT=Path(__file__).resolve().parents[1];TASK=ROOT/'QCI_4_Edge_Telemetry';REPORTS=ROOT/'reports/qci4'

def write(path,value):path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def now():return datetime.fromtimestamp(time.time(),timezone.utc)
def summary(values):
    values=list(values);ordered=sorted(values)
    return {'samples':len(values),'mean_ms':statistics.mean(values),'p95_ms':ordered[min(len(ordered)-1,int(.95*len(ordered)))],
        'min_ms':min(values),'max_ms':max(values)}
def new_runtime(prefix):
    p=TASK/'runtime'/(prefix+'_'+uuid.uuid4().hex[:8]);p.mkdir(parents=True)
    sources=list(TASK.glob('*.py'))+[ROOT/'QCI_2_Defect_Classifier/infer.py',ROOT/'Backend/main.py',ROOT/'Frontend/qci4.py']
    write(p/'execution_sources.json',{'git_head_at_start':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'files':{f.relative_to(ROOT).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in sources}})
    return p
def local_config(directory,mock,**extra):
    values=dict(database=str(directory/'edge.db'),alerts_database=str(directory/'edge.db'),cloud_enabled=True,
        cloud_base_url=mock.url,health_path='/health',sync_path='/sync',expected_service='qci4-sync-v1',
        allow_event_sync=True,allow_telemetry_sync=True,receiver_idempotent=True,request_timeout_seconds=.5,
        sample_interval_seconds=.1,health_interval_seconds=.1,backoff_base_seconds=.05,backoff_max_seconds=.2,jitter_fraction=0,
        replay_items_per_second=100,minimum_disk_free_bytes=0,receipt_capacity=512)
    values.update(extra);return Config(**values)

def wait_for(predicate,seconds=10):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        value=predicate()
        if value:return value
        time.sleep(.02)
    raise RuntimeError('Measured integration condition timed out')

def demo():
    import cv2,numpy as np
    cv2.setNumThreads(1);cv2.resize(np.zeros((2,2),np.float32),(3,3))
    from QCI_2_Defect_Classifier.common import deterministic
    from QCI_2_Defect_Classifier.infer import DefectClassifier
    deterministic();directory=new_runtime('demo');tracker=InferenceTracker()
    references=json.loads((ROOT/'reports/qci2/test_predictions.json').read_text())
    chosen=[next(r for r in references if r['ground_truth']==i) for i in (0,1)]
    records=[json.loads(line) for line in (ROOT/'reports/qci1/segmentation/samples.jsonl').read_text().splitlines()]
    images=[ROOT/'QCI_1_Surface_Defect_Segmentation/runtime/segmentation_dataset'/next(r['image']['path'] for r in records if r['sample_id']==reference['sample_id']) for reference in chosen]
    artifact=json.loads((ROOT/'reports/qci2/model_artifact.json').read_text())
    phases=[];baseline=[];monitored=[];alarm_latency=[];queue_write=[];http_latencies=[]
    handles_before=psutil.Process().num_handles() if hasattr(psutil.Process(),'num_handles') else psutil.Process().num_fds()
    threads_before=threading.active_count()
    with MockCloud(directory/'receiver.db',capture_capacity=128) as mock,loopback_only() as blocked:
        classifier=DefectClassifier(ROOT/artifact['checkpoint'],artifact['sha256'],telemetry=tracker)
        for image in images:
            assert classifier.predict(dict(image=str(image),heatmap=True)).status=='SUCCESS'
        for i in range(12):
            t=time.perf_counter();result=classifier.predict(dict(image=str(images[i%2]),heatmap=True));baseline.append((time.perf_counter()-t)*1000)
            assert result.status=='SUCCESS'
        config=local_config(directory,mock,sample_interval_seconds=2);service=EdgeService(config,tracker=tracker)
        alarms=AlarmEngine(AlarmConfig(database=config.alerts_database,active_capacity=64,
            rules={'normal':Rule(initial='info'),'defect':Rule(initial='warning',source_overrides={'demo.critical':'critical'})}))
        transport=service.worker.client.request
        def timed(*args,**kwargs):
            result=transport(*args,**kwargs)
            if args[0]=='POST':http_latencies.append(result.latency_ms)
            return result
        service.worker.client.request=timed
        service.start()
        try:
            wait_for(lambda:service.worker.snapshot().status==CloudStatus.ONLINE)
            phases.append({'phase':'online','snapshot':service.collector.status().model_dump(mode='json')})
            mock.health_online=False;mock.codes=deque([503]);failure_started=time.perf_counter()
            wait_for(lambda:service.worker.snapshot().status==CloudStatus.OFFLINE)
            detection_ms=(time.perf_counter()-failure_started)*1000
            phases.append({'phase':'offline','snapshot':service.collector.sample().model_dump(mode='json')})
            cpu_before=psutil.Process().cpu_times();wall_before=time.perf_counter()
            for i in range(12):
                t=time.perf_counter();prediction=classifier.predict(dict(image=str(images[i%2]),heatmap=True));monitored.append((time.perf_counter()-t)*1000)
                assert prediction.status=='SUCCESS' and prediction.heatmap is not None
                assert abs(prediction.confidence-chosen[i%2]['prediction']['confidence'])<1e-6
                source='demo.critical' if i%2 else 'demo.normal'
                event=Event(source_id=source,event_id=f'actual-{i}',sequence=0,observed_at=now(),prediction=prediction)
                t=time.perf_counter();status=alarms.process(event);alarm_latency.append((time.perf_counter()-t)*1000)
                assert status.state.value==('critical' if i%2 else 'info')
                if i%2:alarms.resolve(Resolve(source_id=source,event_id=event.event_id,observed_at=now()))
            service.collector.sample();before_recovery=service.spool.stats()
            phases.append({'phase':'queued_during_outage','snapshot':service.collector.status().model_dump(mode='json')})
            assert before_recovery.pending>=18 and service.worker.snapshot().mode.value=='LOCAL_ONLY'
            restored_at=time.perf_counter();mock.codes=deque([200]);mock.health_online=True
            seen_recovering=False
            while time.perf_counter()-restored_at<20:
                state=service.worker.snapshot().status;seen_recovering=seen_recovering or state==CloudStatus.RECOVERING
                if state==CloudStatus.RECOVERING and not any(p['phase']=='recovering' for p in phases):
                    phases.append({'phase':'recovering','snapshot':service.collector.status().model_dump(mode='json')})
                if state==CloudStatus.ONLINE and service.spool.stats().pending+service.spool.stats().in_flight==0:break
                time.sleep(.02)
            else:raise RuntimeError('Actual recovery backlog did not drain')
            recovery_ms=(time.perf_counter()-restored_at)*1000
            final=service.collector.sample();phases.append({'phase':'restored','snapshot':final.model_dump(mode='json')})
            assert seen_recovering and final.inference.inference_count==26
            assert final.inference.model_loaded and final.inference.status=='HEALTHY'
            assert final.alerts.active_info==6 and final.alerts.active_critical==0
            assert mock.receipt_count()==service.spool.stats().delivered_total
            event_receipts=[r for r in mock.receipts() if json.loads(r[3])['kind']=='event_summary']
            assert len(event_receipts)==18
            ordered={}
            for row in event_receipts:
                p=json.loads(row[3]);ordered.setdefault(p['activation_key'],[]).append(p['state'])
            assert sum(states==['critical','resolved'] for states in ordered.values())==6
            cpu_after=psutil.Process().cpu_times();wall=time.perf_counter()-wall_before
            endpoint_times=[]
            for _ in range(50):
                t=time.perf_counter();service.collector.status().model_dump(mode='json');endpoint_times.append((time.perf_counter()-t)*1000)
            with closing(sqlite3.connect(service.spool.path)) as db:
                queue_write=[json.loads(r[0]).get('latency_ms') for r in db.execute("SELECT fields FROM qci4_log WHERE code='TELEMETRY_SAMPLE'")]
            queue_write=[x for x in queue_write if x is not None]
            result={'config':config.model_dump(mode='json'),'production_cloud_endpoint_provided':False,
                'cloud_contract':'explicit local mock protocol; no production service validation claimed',
                'model_version':artifact['version'],'model_sha256':artifact['sha256'],'fresh_model_predictions_during_outage':12,
                'fresh_cam_outputs_during_outage':12,'prediction_numerical_parity_verified':True,
                'source_images_used':[p.relative_to(ROOT).as_posix() for p in images],
                'active_local_info_after_outage':6,'critical_activations_during_outage':6,'explicit_critical_resolutions':6,
                'pending_before_recovery':before_recovery.model_dump(mode='json'),'final_spool':service.spool.stats().model_dump(mode='json'),
                'event_summaries_delivered':18,'requests_received':mock.attempt_count,'logical_items_received':mock.receipt_count(),
                'duplicate_logical_deliveries':0,'ordered_critical_then_resolved_verified':True,
                'failure_detection_ms':detection_ms,'recovery_ms':recovery_ms,'recovering_observed':seen_recovering,
                'baseline_classifier_plus_cam':summary(baseline),'monitored_classifier_plus_cam':summary(monitored),
                'observed_inference_mean_change_percent':(statistics.mean(monitored)-statistics.mean(baseline))/statistics.mean(baseline)*100,
                'alarm_core_latency':summary(alarm_latency),'status_handler_latency':summary(endpoint_times),
                'telemetry_collection_latency':summary(queue_write),'cloud_post_latency':summary(http_latencies),
                'process_cpu_seconds_during_monitored_phase':(cpu_after.user+cpu_after.system)-(cpu_before.user+cpu_before.system),
                'monitored_phase_wall_seconds':wall,'external_tcp_attempts':len(blocked),'physical_network_disconnected':False,
                'phases':phases,'database':service.spool.path.relative_to(ROOT).as_posix(),
                'receiver_database':mock.database.relative_to(ROOT).as_posix(),
                'pid':psutil.Process().pid,'gpu_used':False}
        finally:service.stop()
        assert not service.collector.thread.is_alive() and not service.worker.thread.is_alive()
    result['threads_before']=threads_before;result['threads_after']=threading.active_count()
    result['handles_before']=handles_before;result['handles_after']=psutil.Process().num_handles() if hasattr(psutil.Process(),'num_handles') else psutil.Process().num_fds()
    result['owned_workers_stopped']=True
    write(REPORTS/'failover_demo.json',result)
    print(json.dumps({k:result[k] for k in ('fresh_model_predictions_during_outage','event_summaries_delivered','duplicate_logical_deliveries','failure_detection_ms','recovery_ms','observed_inference_mean_change_percent','owned_workers_stopped')}),flush=True)

def profile():
    directory=new_runtime('profile');p=psutil.Process();samples=[];phase=['warmup'];stop=threading.Event()
    core=deque(maxlen=1024);collect=deque(maxlen=1024);post=deque(maxlen=1024);enqueue_times=deque(maxlen=1024)
    reference=next(r['prediction'] for r in json.loads((ROOT/'reports/qci2/test_predictions.json').read_text()) if r['ground_truth']==1)
    with MockCloud(directory/'receiver.db',capture_capacity=16) as mock,loopback_only() as blocked:
        config=local_config(directory,mock,allow_telemetry_sync=False,history_capacity=300,receipt_capacity=512,request_timeout_seconds=1)
        service=EdgeService(config,tracker=InferenceTracker())
        alarm=AlarmEngine(AlarmConfig(database=config.alerts_database,active_capacity=32,record_capacity=256,audit_capacity=1000,
            resolved_ttl_seconds=1,rules={'normal':Rule(initial='info'),'defect':Rule(initial='critical')}))
        request=service.worker.client.request
        def measured(*args,**kwargs):
            result=request(*args,**kwargs)
            if args[0]=='POST':post.append(result.latency_ms)
            return result
        service.worker.client.request=measured
        enqueue=service.spool.enqueue_batch
        def measured_enqueue(*args,**kwargs):
            t=time.perf_counter()
            try:return enqueue(*args,**kwargs)
            finally:enqueue_times.append((time.perf_counter()-t)*1000)
        service.spool.enqueue_batch=measured_enqueue
        def sample_rss():
            while not stop.is_set():
                samples.append((time.monotonic(),phase[0],p.memory_info().rss/2**20,p.num_threads(),p.num_handles() if hasattr(p,'num_handles') else p.num_fds()))
                stop.wait(.05)
        thread=threading.Thread(target=sample_rss,name='qci4-rss-proof');thread.start()
        start=p.memory_info().rss/2**20;before_threads=p.num_threads();before_handles=p.num_handles() if hasattr(p,'num_handles') else p.num_fds()
        try:
            for i in range(1300):
                phase[0]='warmup' if i<300 else 'first' if i<800 else 'second'
                mock.health_online=False;service.worker.tick(force_health=True);service.worker.tick(force_health=True)
                assert service.worker.snapshot().mode.value=='LOCAL_ONLY'
                t=time.perf_counter();alarm.process(Event(source_id='profile',event_id=f'cycle-{i}',sequence=0,observed_at=now(),prediction=reference));core.append((time.perf_counter()-t)*1000)
                alarm.resolve(Resolve(source_id='profile',event_id=f'cycle-{i}',observed_at=now()))
                snapshot=service.collector.sample();collect.append(snapshot.collection_latency_ms)
                assert service.spool.stats().pending==2
                mock.health_online=True;service.worker.next_send=0;service.worker.tick(force_health=True)
                recovery_deadline=time.monotonic()+8
                while service.spool.stats().pending+service.spool.stats().in_flight:
                    if time.monotonic()>=recovery_deadline:raise RuntimeError('Actual bounded retry failed to recover profile backlog')
                    if service.spool.stats().failed_permanent+service.spool.stats().unknown:raise RuntimeError('A required profile item exhausted its real retry budget')
                    time.sleep(.01);service.worker.tick()
                assert service.worker.snapshot().status==CloudStatus.ONLINE and service.spool.stats().pending==0
            assert mock.receipt_count()==2600 and blocked==[]
        finally:stop.set();thread.join(timeout=2)
        end=p.memory_info().rss/2**20;after_threads=p.num_threads();after_handles=p.num_handles() if hasattr(p,'num_handles') else p.num_fds()
        first=[r[2] for r in samples if r[1]=='first'];second=[r[2] for r in samples if r[1]=='second']
        drift=abs(statistics.mean(second)-statistics.mean(first))/statistics.mean(first)*100
        result={'cycles':1300,'warmup_cycles':300,'cycles_per_matched_window':500,'sampling_hz':20,
            'method':'continuous whole-process RSS; manual accelerated real-HTTP state cycles; no classifier loaded; background worker lifecycle separately tested and used in real-model demo',
            'profile_events':'replay of verified QCI-2 result through actual QCI-3 state; not 1300 fresh model inferences',
            'start_rss_mib':start,'peak_rss_mib':max(r[2] for r in samples),'end_rss_mib':end,
            'first_window_mean_rss_mib':statistics.mean(first),'second_window_mean_rss_mib':statistics.mean(second),
            'matched_window_drift_percent':drift,'strict_less_than_5_percent_pass':drift<5,
            'raw_endpoint_change_percent':abs(end-start)/start*100,'threads_before':before_threads,'threads_after':after_threads,
            'handles_before':before_handles,'handles_after':after_handles,'peak_threads':max(r[3] for r in samples),'peak_handles':max(r[4] for r in samples),
            'receiver_capture_capacity':16,'receiver_attempts':mock.attempt_count,'receiver_logical_receipts':mock.receipt_count(),
            'logical_items_delivered':service.spool.stats().delivered_total,'duplicate_logical_items':0,
            'history_retained':len(service.collector.history),'history_capacity':config.history_capacity,'spool':service.spool.stats().model_dump(mode='json'),
            'telemetry_latency':summary(collect),'local_alarm_latency':summary(core),'spool_enqueue_latency':summary(enqueue_times),'cloud_post_latency':summary(post),
            'latency_sampling':'latest 1024 timings retained; spool timing includes entire bounded batch transaction and commit; no SLA invented',
            'runtime_database':service.spool.path.relative_to(ROOT).as_posix(),'receiver_database':mock.database.relative_to(ROOT).as_posix(),
            'external_tcp_attempts':len(blocked),'config':config.model_dump(mode='json')}
    with (REPORTS/'memory_samples.csv').open('w',encoding='utf-8',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(['monotonic_seconds','phase','rss_mib','threads','handles']);writer.writerows(samples)
    write(REPORTS/'memory_profile.json',result)
    if drift>=5:raise RuntimeError('Actual matched-window RSS drift exceeds strict 5% gate')
    print(json.dumps({k:result[k] for k in ('cycles','matched_window_drift_percent','strict_less_than_5_percent_pass','logical_items_delivered','threads_before','threads_after','handles_before','handles_after')}),flush=True)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['demo','profile']);args=parser.parse_args()
    REPORTS.mkdir(parents=True,exist_ok=True);(TASK/'runtime').mkdir(parents=True,exist_ok=True)
    demo() if args.mode=='demo' else profile()
if __name__=='__main__':main()
