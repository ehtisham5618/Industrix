"""Measure real localhost FastAPI health requests and standalone collector cost."""
from pathlib import Path
import http.client
import json
import socket
import threading
import time
import uuid
import psutil
import uvicorn
from fastapi import FastAPI
from . import api
from .contracts import Config
from .verify import summary,write
from QCI_3_Severity_IoT.offline import loopback_only

ROOT=Path(__file__).resolve().parents[1];REPORTS=ROOT/'reports/qci4'

def main():
    runtime=ROOT/'QCI_4_Edge_Telemetry/runtime'/('api_'+uuid.uuid4().hex[:8]);runtime.mkdir(parents=True)
    demo=json.loads((REPORTS/'failover_demo.json').read_text())
    service=api.EdgeService(Config(database=str(runtime/'edge.db'),alerts_database=str(ROOT/demo['database'])))
    app=FastAPI();app.include_router(api.router);api._INSTANCE=service
    listener=socket.socket();listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,log_level='error',lifespan='off',access_log=False))
    thread=threading.Thread(target=lambda:server.run(sockets=[listener]),name='qci4-api-proof',daemon=False)
    process=psutil.Process();requests=[];collection=[];service.start()
    with loopback_only() as external:
        thread.start()
        try:
            deadline=time.monotonic()+5
            while not server.started:
                if time.monotonic()>deadline:raise RuntimeError('Local API did not start')
                time.sleep(.01)
            for i in range(60):
                connection=http.client.HTTPConnection('127.0.0.1',port,timeout=2);began=time.perf_counter()
                try:
                    connection.request('GET','/edge/status');response=connection.getresponse();body=response.read(65537)
                    assert response.status==200 and len(body)<=65536
                    data=json.loads(body);assert data['cloud']['status']=='DISABLED' and data['local_ai_requires_cloud'] is False
                finally:connection.close()
                if i>=10:requests.append((time.perf_counter()-began)*1000)
            before=process.cpu_times();rss_before=process.memory_info().rss/2**20;start=time.perf_counter()
            for _ in range(50):
                value=service.collector.sample();collection.append(value.collection_latency_ms)
            after=process.cpu_times();wall=time.perf_counter()-start;rss_after=process.memory_info().rss/2**20
            result={'endpoint':f'http://127.0.0.1:{port}/edge/status','actual_http_requests':60,'warmup_requests':10,
                'http_endpoint_latency':summary(requests),'standalone_collector_latency':summary(collection),
                'collector_cpu_seconds_for_50_samples':after.user+after.system-before.user-before.system,
                'collector_batch_wall_seconds':wall,'collector_rss_before_mib':rss_before,'collector_rss_after_mib':rss_after,
                'measurement_note':'Shared process includes local API threads and the 2s sampler; no classifier in this process; counters not invented from saved model reports.',
                'last_actual_response':data,'last_collector_snapshot':value.model_dump(mode='json'),
                'external_tcp_attempts':len(external),'cloud_calls_attempted':0}
            write(REPORTS/'api_profile.json',result)
            print(json.dumps({k:result[k] for k in ('actual_http_requests','http_endpoint_latency','standalone_collector_latency','collector_cpu_seconds_for_50_samples')}))
        finally:
            server.should_exit=True;thread.join(timeout=5);listener.close();service.stop();api._INSTANCE=None
        if thread.is_alive():raise RuntimeError('Local API proof server did not stop')
if __name__=='__main__':main()
