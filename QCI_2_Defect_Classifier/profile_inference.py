"""Repeated real inference/Grad-CAM RSS and latency profiling without map caching."""
from __future__ import annotations
import csv
import gc
import json
import threading
import time
from pathlib import Path
import numpy as np
import psutil
from QCI_1_Surface_Defect_Segmentation.offline import no_network
from .common import REPORTS,TASK,deterministic,load_config,write_json
from .data import ManifestDataset
from .infer import DefectClassifier


def main() -> int:
    """Warm20 real calls, compare two complete240-call matched validation cycles."""
    config=load_config(TASK/'configs/qci2_classifier.yaml');deterministic(config.seed,config.threads)
    dataset=ManifestDataset(config,'val');service=DefectClassifier(config.output_dir/'best.pt')
    process=psutil.Process();stop=threading.Event();peak=0.;samples=0;lock=threading.Lock()
    def watch() -> None:
        nonlocal peak,samples
        while not stop.is_set():
            rss=process.memory_info().rss/2**20
            with lock:peak=max(peak,rss);samples+=1
            stop.wait(.05)
    thread=threading.Thread(target=watch,name='qci2-rss',daemon=True)
    classifier_ms=[];cam_ms=[];combined_ms=[];cycles=[];degenerate=0
    try:
        with no_network() as network:
            for i in range(20):
                row=dataset.rows[i%len(dataset)];result=service.predict(dict(image=str(dataset.root/row.image.path)))
                if result.status!='SUCCESS':raise ValueError(result.error_message)
            del result;gc.collect();start_rss=process.memory_info().rss/2**20;thread.start();before=time.perf_counter()
            with (REPORTS/'inference_memory_samples.csv').open('w',encoding='utf-8',newline='') as stream:
                writer=csv.writer(stream);writer.writerow(['cycle','sample_id','rss_mib','classifier_ms','heatmap_ms','combined_ms','degenerate'])
                for cycle in (1,2):
                    rss_sum=count=0
                    for repeat in range(5):
                        for row in dataset.rows:
                            result=service.predict(dict(image=str(dataset.root/row.image.path)))
                            if result.status!='SUCCESS':raise ValueError(result.error_message)
                            rss=process.memory_info().rss/2**20;rss_sum+=rss;count+=1
                            classifier_ms.append(result.classifier_latency_ms);cam_ms.append(result.heatmap_latency_ms);combined_ms.append(result.combined_latency_ms)
                            degenerate+=int(result.heatmap.degenerate)
                            writer.writerow([cycle,row.sample_id,rss,result.classifier_latency_ms,result.heatmap_latency_ms,result.combined_latency_ms,result.heatmap.degenerate])
                            if service.target_layer._forward_hooks or any(p.grad is not None for p in service.model.parameters()):raise ValueError('Attribution state leaked')
                            del result
                    cycles.append(dict(cycle=cycle,samples=count,mean_rss_mib=rss_sum/count))
                    print('Completed matched inference cycle',cycle,cycles[-1],flush=True)
            elapsed=time.perf_counter()-before;gc.collect();end_rss=process.memory_info().rss/2**20
        stop.set();thread.join(timeout=5)
        drift=abs(cycles[-1]['mean_rss_mib']-cycles[0]['mean_rss_mib'])/cycles[0]['mean_rss_mib']*100
        def latency(values: list[float]) -> dict[str,float]:
            return dict(mean_ms=float(np.mean(values)),p95_ms=float(np.percentile(values,95)),minimum_ms=min(values),maximum_ms=max(values))
        result=dict(workload='Actual best checkpoint, full-image classification plus genuine Grad-CAM; no retained maps or disk export',
            warmup_calls=20,measured_calls=len(combined_ms),validation_samples=len(dataset),repeats_per_cycle=5,start_rss_mib=start_rss,peak_rss_mib=peak,
            end_rss_mib=end_rss,cycles=cycles,drift_percent=drift,strict_under_5_percent_pass=drift<5,
            method='abs(last matched full-workload mean RSS-first matched mean RSS)/first mean*100 after20 warm calls; identical ordered48-sample mixes,240 calls per window',
            continuous_peak_interval_seconds=.05,continuous_rss_samples=samples,duration_seconds=elapsed,
            classifier_latency=latency(classifier_ms),heatmap_latency=latency(cam_ms),combined_latency=latency(combined_ms),
            degenerate_heatmaps=degenerate,remaining_hooks=0,retained_parameter_gradients=0,offline_verified=True,external_connection_attempts=network.attempts,runtime_downloads=0,numeric_latency_sla=None)
        write_json(REPORTS/'inference_profile.json',result);print(json.dumps(result,indent=2));return 0 if drift<5 else 1
    finally:
        stop.set()
        if thread.is_alive():thread.join(timeout=5)


if __name__=='__main__':raise SystemExit(main())
