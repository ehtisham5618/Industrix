"""Dedicated actual-source RSS profile using the same scan/preprocess function."""
from __future__ import annotations

import argparse
import csv
import gc
import json
import sqlite3
import time
import threading
from collections import deque
from pathlib import Path
from statistics import mean

import psutil

from .config import ROOT,load_config,read_mapping
from .discovery import SamplePlan
from .offline import no_network
from .pipeline import scan_sample


def plan_from_row(row: sqlite3.Row, root: Path) -> SamplePlan:
    """Reconstruct actual paths from the completed disk manifest, not guesses."""
    sample=json.loads(row['result'])
    return SamplePlan(sample['sample_id'].split('/',1)[1],root/sample['image']['path'],
        root/sample['annotation_path'] if sample['annotation_path'] else None,sample['split'],False,False)


def main(argv: list[str] | None = None) -> int:
    """Warm largest sources, then measure full-source stable-window RSS drift."""
    parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,default=ROOT/'QCI_1_Surface_Defect_Segmentation/configs/qci1_segmentation.yaml')
    parser.add_argument('--passes',type=int,default=2)
    args=parser.parse_args(argv);config=load_config(args.config);mapping,_=read_mapping(config)
    indices=sorted(config.output_dir.glob('index_*.sqlite'))
    if not indices:raise ValueError('Run the actual source ingestion before profiling')
    db=sqlite3.connect(indices[-1]);db.row_factory=sqlite3.Row;db.execute('PRAGMA cache_size=-2048');db.execute('PRAGMA temp_store=FILE')
    if args.passes<2 or args.passes>5:raise ValueError('Compare 2..5 complete identical source passes')
    process=psutil.Process();peak=0.;sampler_stop=threading.Event();sample_lock=threading.Lock();sample_count=0;sample_sum=0.
    def sample_rss() -> None:
        nonlocal peak,sample_count,sample_sum
        while not sampler_stop.is_set():
            rss=process.memory_info().rss/(1024*1024)
            with sample_lock:peak=max(peak,rss);sample_count+=1;sample_sum+=rss
            sampler_stop.wait(.05)
    sampler=threading.Thread(target=sample_rss,name='qci1-rss',daemon=True)
    started=time.perf_counter();count=0;valid=0;elapsed_total=0.;rss_sum=0.;rss_count=0
    try:
        with no_network() as network:
            # Maximum-area source images establish decoder/allocator high-water
            # behavior before measuring. Warm-up is reported, not called a pass.
            warm=0
            for row in db.execute('SELECT result FROM samples WHERE source_valid=1 ORDER BY width*height DESC,path LIMIT 64'):
                scan_sample(plan_from_row(row,config.dataset_root),config,mapping);warm+=1
            gc.collect();start_rss=process.memory_info().rss/(1024*1024);sampler.start();cycles=[]
            with (config.output_dir/'memory_samples.csv').open('w',encoding='utf-8',newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=['pass','processed','elapsed_seconds','rss_mib','sample_ms','source_valid']);writer.writeheader()
                measure_start=time.perf_counter()
                for cycle in range(1,args.passes+1):
                    cycle_sum=0.;cycle_count=0
                    for row in db.execute('SELECT result FROM samples ORDER BY sample_id,path'):
                        before=time.perf_counter();sample,_=scan_sample(plan_from_row(row,config.dataset_root),config,mapping)
                        seconds=time.perf_counter()-before;count+=1;valid+=int(sample.source_valid);elapsed_total+=seconds
                        rss=process.memory_info().rss/(1024*1024);rss_sum+=rss;rss_count+=1;cycle_sum+=rss;cycle_count+=1
                        writer.writerow({'pass':cycle,'processed':count,'elapsed_seconds':time.perf_counter()-measure_start,'rss_mib':rss,'sample_ms':seconds*1000,'source_valid':sample.source_valid})
                        if count%500==0:print('Pass',cycle,'profiled',count,'actual source evaluations; RSS',round(rss,2),'MiB',flush=True)
                    cycles.append(dict(pass_=cycle,samples=cycle_count,post_sample_mean_rss_mib=cycle_sum/cycle_count))
                elapsed=time.perf_counter()-measure_start
            gc.collect();end_rss=process.memory_info().rss/(1024*1024)
            sampler_stop.set();sampler.join(timeout=5)
        if not count:raise ValueError('No source samples for memory profile')
        stable_start=cycles[0]['post_sample_mean_rss_mib'];stable_end=cycles[-1]['post_sample_mean_rss_mib'];drift=abs(stable_end-stable_start)/stable_start*100
        result=dict(workload=('Actual image/indexed-mask validation and RGB/mask preprocessing' if config.annotation_format=='indexed_mask' else 'Actual source image/annotation validation and RGB preprocessing; no genuine production masks are present'),
            source_index=indices[-1].name,samples=count,source_valid=valid,warmup_largest_samples=warm,warmup_seconds=measure_start-started,
            start_rss_mib=start_rss,mean_rss_mib=rss_sum/rss_count,peak_rss_mib=peak,end_rss_mib=end_rss,
            stable_window_samples=cycles[0]['samples'],passes=cycles,stable_start_mean_mib=stable_start,stable_end_mean_mib=stable_end,drift_percent=drift,strict_under_5_percent_pass=drift<5,
            continuous_sampling_interval_seconds=.05,continuous_rss_samples=sample_count,continuous_mean_rss_mib=sample_sum/max(1,sample_count),
            method='abs(last_complete_pass_mean_RSS-first_complete_pass_mean_RSS)/first_complete_pass_mean_RSS*100 after warming 64 largest-area sources; identical complete ordered source mix in each window; one sample live; transient peak sampled at 20 Hz',
            duration_seconds=elapsed,samples_per_second=count/elapsed,mean_sample_processing_ms=elapsed_total/count*1000,
            offline_verified=True,external_connection_attempts=network.attempts,numeric_latency_sla=None)
        (config.output_dir/'memory_profile.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(result,indent=2));return 0 if drift<5 and network.attempts==0 else 1
    finally:
        sampler_stop.set()
        if sampler.is_alive():sampler.join(timeout=5)
        db.close()


if __name__=='__main__':raise SystemExit(main())
