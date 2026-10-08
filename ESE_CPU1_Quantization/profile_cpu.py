"""Profile legitimate thread settings before the full official benchmark."""
import json
from pathlib import Path
import time

from .common import ROOT,REPORTS,RUNTIME,preprocess,digest,write_json
from .benchmark import latency_summary


def main():
    import cv2
    import openvino as ov
    image=Path((RUNTIME/'calibration_images.txt').read_text().splitlines()[0])
    tensor=preprocess(cv2.imread(str(image)))
    xml=ROOT/'Backend/weights/openvino_int8/model.xml'
    results={}
    for threads in (1,2,4):
        compiled=ov.Core().compile_model(str(xml),'CPU',{
            'PERFORMANCE_HINT':'LATENCY','NUM_STREAMS':1,'INFERENCE_NUM_THREADS':threads})
        for _ in range(20):compiled([tensor])
        samples=[]
        for _ in range(50):
            start=time.perf_counter_ns();compiled([tensor])
            samples.append((time.perf_counter_ns()-start)/1e6)
        results[str(threads)]=latency_summary(samples,20,threads)
        print('Thread profile',threads,results[str(threads)],flush=True)
    selected=int(min(results,key=lambda name:results[name]['mean_ms']))
    write_json(REPORTS/'cpu_thread_profile.json',dict(results=results,selected_threads=selected,
        xml_sha256=digest(xml),bin_sha256=digest(xml.with_suffix('.bin')),
        note='Preliminary hardware-only tuning on one training image; official200-call benchmark follows'))


if __name__=='__main__':main()
