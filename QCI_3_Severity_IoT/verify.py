"""Measured QCI-2 -> local state -> real loopback receiver proof and RSS stress."""
from __future__ import annotations
from datetime import datetime,timedelta,timezone
import argparse
import csv
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import threading
import time
import uuid
import psutil
from .contracts import Config,Rule,Event,Resolve,WebhookConfig,Delivery
from .engine import AlarmEngine
from .webhook import WebhookWorker
from .mock_receiver import MockReceiver
from .offline import loopback_only

ROOT=Path(__file__).resolve().parents[1];REPORTS=ROOT/'reports/qci3';TASK=ROOT/'QCI_3_Severity_IoT'

def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf-8')

def summary(values):
    ordered=sorted(values)
    return {'samples':len(values),'mean_ms':statistics.mean(values),'p95_ms':ordered[min(len(ordered)-1,int(.95*len(ordered)))],
        'min_ms':min(values),'max_ms':max(values)}

def fresh_predictions():
    """Execute actual classifier/CAM in its own process, outside the alarm engine."""
    output=TASK/'runtime'/'fresh_predictions.json'
    code='''from pathlib import Path
import json
import cv2,numpy as np
cv2.setNumThreads(1);cv2.resize(np.zeros((2,2),np.float32),(3,3))
from QCI_2_Defect_Classifier.common import deterministic
from QCI_2_Defect_Classifier.infer import DefectClassifier
from QCI_1_Surface_Defect_Segmentation.offline import no_network
root=Path.cwd();deterministic()
references=json.loads((root/'reports/qci2/test_predictions.json').read_text())
chosen=[next(r for r in references if r['ground_truth']==i) for i in (0,1)]
artifact=json.loads((root/'reports/qci2/model_artifact.json').read_text())
with no_network() as audit:
 service=DefectClassifier(root/artifact['checkpoint'],artifact['sha256'])
 rows=[]
 for reference in chosen:
  split,item,part=reference['sample_id'].split('/')
  image=root/'QCI_1_Surface_Defect_Segmentation/runtime/segmentation_dataset/images'/split/item/(part+'.jpg')
  if not image.is_file():
   # Preserve the dataset's actual flat directory convention, using its manifest.
   records=[json.loads(line) for line in (root/'reports/qci1/segmentation/samples.jsonl').read_text().splitlines()]
   record=next(r for r in records if r['sample_id']==reference['sample_id'])
   image=root/'QCI_1_Surface_Defect_Segmentation/runtime/segmentation_dataset'/record['image']['path']
  prediction=service.predict(dict(image=str(image),output_dir=str(root/'QCI_3_Severity_IoT/runtime/heatmaps')))
  assert prediction.status=='SUCCESS',prediction.error_message
  assert prediction.predicted_class_id==reference['prediction']['predicted_class_id']
  assert abs(prediction.confidence-reference['prediction']['confidence'])<1e-6
  rows.append(dict(source_sample_id=reference['sample_id'],prediction=prediction.model_dump(mode='json')))
 assert audit.attempts==0
(root/'QCI_3_Severity_IoT/runtime/fresh_predictions.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
print(json.dumps(dict(actual_fresh_classifier_cam=True,samples=len(rows),external_tcp_attempts=audit.attempts)))
'''
    result=subprocess.run([sys.executable,'-X','utf8','-c',code],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=120)
    (REPORTS/'fresh_classifier_terminal.txt').write_text(result.stdout+result.stderr,encoding='utf-8')
    if result.returncode:raise RuntimeError('Actual classifier bridge failed; terminal evidence retained')
    return json.loads(output.read_text(encoding='utf-8'))

def demo(predictions):
    directory=TASK/'runtime'/('demo_'+uuid.uuid4().hex[:8]);directory.mkdir(parents=True)
    local=[];http=[];dispatch=[];states=[]
    with MockReceiver(codes=(500,200)) as receiver,loopback_only() as attempts:
        config=Config(database=str(directory/'events.db'),policy_version='qci3-loopback-demo-v1',
            rules={'normal':Rule(initial='info'),'defect':Rule(initial='warning',source_overrides={'demo.critical':'critical'})},
            webhook=WebhookConfig(enabled=True,url=receiver.url,timeout_seconds=1,attempts=3,receiver_idempotent=True,backoff_seconds=0))
        engine=AlarmEngine(config);worker=WebhookWorker(engine)
        send=worker._send
        def timed(payload):
            started=time.perf_counter()
            try:return send(payload)
            finally:http.append((time.perf_counter()-started)*1000)
        worker._send=timed
        for i in range(102):
            p=predictions[0 if i==0 else 1]
            source='demo.normal' if i==0 else 'demo.warning' if i==1 else 'demo.critical'
            event=Event(source_id=source,event_id=f'actual-{i}',sequence=0,observed_at=datetime.now(timezone.utc),prediction=p['prediction'])
            t=time.perf_counter();result=engine.process(event);local.append((time.perf_counter()-t)*1000)
            states.append(result.model_dump(mode='json'))
            for _ in range(3):
                t=time.perf_counter();worker.run_once();dispatch.append((time.perf_counter()-t)*1000)
            for _ in range(10):assert engine.process(event).duplicate
            engine.resolve(Resolve(source_id=source,event_id=event.event_id,observed_at=datetime.now(timezone.utc)))
        assert len(receiver.received)==101 and len(receiver.activations)==100
        assert all(engine.get('demo.critical',f'actual-{i}').delivery==Delivery.ACKNOWLEDGED for i in range(2,102))
        proof={'real_classifier_results_consumed':True,'model_version':config.expected_model_version,
            'policy':config.model_dump(mode='json'),'policy_scope':'explicit software research/demo source override; not factory rule approval',
            'mock_url':receiver.url,'external_tcp_attempts':len(attempts),'physical_internet_disconnected':False,
            'internet_guard':'process-local external TCP blocked; numeric loopback allowed; not an OS firewall',
            'requests_received':len(receiver.received),'acknowledged_activations':len(receiver.activations),
            'duplicate_inputs':1020,'duplicate_activations':0,'http_500_retries':1,
            'core_latency':summary(local),'http_latency':summary(http),'worker_dispatch_latency':summary(dispatch),
            'decision_latency':summary([s['decision_latency_ms'] for s in states]),
            'transition_latency':summary([s['transition_latency_ms'] for s in states]),
            'local_action_latency':summary([s['local_action_latency_ms'] for s in states]),
            'first_states':states[:3],'received_payloads':receiver.received[:3],
            'audit_database':str((directory/'events.db').relative_to(ROOT))}
        write(REPORTS/'loopback_demo.json',proof);return proof

def memory(predictions):
    directory=TASK/'runtime'/('profile_'+uuid.uuid4().hex[:8]);directory.mkdir(parents=True)
    engine=AlarmEngine(Config(database=str(directory/'events.db'),active_capacity=32,record_capacity=256,
        audit_capacity=1000,resolved_ttl_seconds=1))
    process=psutil.Process();samples=[];stop=threading.Event();phase=['warmup'];latencies=[]
    def sampler():
        while not stop.is_set():
            samples.append((time.monotonic(),phase[0],process.memory_info().rss/2**20));stop.wait(.05)
    thread=threading.Thread(target=sampler);thread.start()
    start=process.memory_info().rss/2**20
    try:
        with loopback_only() as attempts:
            for i in range(5500):
                phase[0]='warmup' if i<500 else 'first' if i<3000 else 'second'
                event=Event(source_id='profile',event_id=f'p-{i}',sequence=0,
                    observed_at=datetime.now(timezone.utc),prediction=predictions[i%2]['prediction'])
                t=time.perf_counter();engine.process(event);latencies.append((time.perf_counter()-t)*1000)
                engine.resolve(Resolve(source_id='profile',event_id=event.event_id,observed_at=datetime.now(timezone.utc)))
            assert attempts==[]
    finally:stop.set();thread.join(timeout=2)
    end=process.memory_info().rss/2**20
    first=[r[2] for r in samples if r[1]=='first'];second=[r[2] for r in samples if r[1]=='second']
    if not first or not second:raise RuntimeError('Missing matched profile windows')
    drift=abs(statistics.mean(second)-statistics.mean(first))/statistics.mean(first)*100
    result={'events':5500,'warmup_events':500,'events_per_matched_window':2500,'sampling_hz':20,
        'start_rss_mib':start,'peak_rss_mib':max(r[2] for r in samples),'end_rss_mib':end,
        'first_window_mean_rss_mib':statistics.mean(first),'second_window_mean_rss_mib':statistics.mean(second),
        'matched_window_drift_percent':drift,'strict_less_than_5_percent_pass':drift<5,
        'raw_endpoint_change_percent':abs(end-start)/start*100,'core_latency':summary(latencies[500:]),
        'method':'continuous process RSS at 20 Hz; two equal 2500-event windows after 500 warmup events; HTTP disabled',
        'retained':engine.snapshot(),'runtime_database':str((directory/'events.db').relative_to(ROOT))}
    with (REPORTS/'memory_samples.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.writer(stream);writer.writerow(['monotonic_seconds','phase','rss_mib']);writer.writerows(samples)
    write(REPORTS/'memory_profile.json',result)
    if drift>=5:raise RuntimeError('Genuine <5% matched-window memory gate failed')
    return result

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--cached-predictions',action='store_true');args=parser.parse_args()
    REPORTS.mkdir(parents=True,exist_ok=True);(TASK/'runtime').mkdir(parents=True,exist_ok=True)
    predictions=json.loads((TASK/'runtime/fresh_predictions.json').read_text()) if args.cached_predictions else fresh_predictions()
    actual=demo(predictions);profile=memory(predictions)
    write(REPORTS/'verification_summary.json',{'demo':actual,'memory':profile})
    print(json.dumps({'actual_classifier_bridge':True,'requests_received':actual['requests_received'],
        'acknowledged_activations':actual['acknowledged_activations'],'duplicate_activations':0,
        'memory_drift_percent':profile['matched_window_drift_percent'],'memory_pass':profile['strict_less_than_5_percent_pass'],
        'core_mean_ms':profile['core_latency']['mean_ms'],'core_p95_ms':profile['core_latency']['p95_ms']}),flush=True)

if __name__=='__main__':main()
