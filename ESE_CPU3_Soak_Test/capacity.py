"""Separately measure ready-tensor OpenVINO capacity and profile CPU settings."""
import argparse
import csv
import json
import time
from datetime import datetime,timezone
from pathlib import Path

from ESE_CPU1_Quantization.common import ROOT,preprocess,write_json
from SED_3_Stress_Testing.scripts.analysis import summarize_values
from .engine import OpenVINODetector


def run(duration=90,profile=True):
    import cv2
    from SED_1_Multi_Camera.scripts.config import load_camera_configs
    out=ROOT/'ESE_CPU3_Soak_Test/reports';out.mkdir(parents=True,exist_ok=True)
    cv2.setNumThreads(1)
    tensors=[]
    for camera in load_camera_configs(ROOT/'SED_1_Multi_Camera/configs/3_cameras.json'):
        capture=cv2.VideoCapture(camera.source);ok,frame=capture.read();capture.release()
        if not ok:raise RuntimeError('Capacity input unavailable')
        tensors.append(preprocess(frame))
    settings=[('LATENCY',2,1)]
    if profile:settings += [('LATENCY',1,1),('LATENCY',4,1),('THROUGHPUT',2,2)]
    configurations=[]
    with (out/'inference_capacity_samples.csv').open('w',newline='',encoding='utf-8') as log:
        writer=csv.DictWriter(log,fieldnames=['configuration','iteration','latency_ms']);writer.writeheader()
        for hint,threads,streams in settings:
            detector=OpenVINODetector(threads=threads,hint=hint,streams=streams)
            for i in range(20):detector.infer_tensor(tensors[i%3])
            label=f'{hint}-threads{threads}-streams{streams}'
            started=time.perf_counter();samples=[]
            if hint=='LATENCY' and threads==2:
                while time.perf_counter()-started<duration:
                    _,elapsed=detector.infer_tensor(tensors[len(samples)%3]);samples.append(elapsed)
                    writer.writerow(dict(configuration=label,iteration=len(samples),latency_ms=elapsed))
            else:
                for i in range(40):
                    _,elapsed=detector.infer_tensor(tensors[i%3]);samples.append(elapsed)
                    writer.writerow(dict(configuration=label,iteration=i,latency_ms=elapsed))
            wall=time.perf_counter()-started
            value=dict(configuration=label,settings=detector.verification['settings'],
                frames=len(samples),wall_seconds=wall,capacity_fps=len(samples)/wall,
                pure_runtime_latency_ms=summarize_values(samples),selected_for_soak=hint=='LATENCY' and threads==2)
            configurations.append(value);detector.close()
            print(json.dumps(value),flush=True)
    result=dict(timestamp_utc=datetime.now(timezone.utc).isoformat(),device='CPU',model='Selected CPU1 INT8',
        mode='Separate synchronous static batch1 ready-tensor inference; no camera pacing/preprocessing/NMS/tracker inside capacity timing',
        caveat='THROUGHPUT hint profile here remains synchronous; it is not a measurement of multi-request asynchronous peak capacity',
        selected_configuration=configurations[0],configuration_profiles=configurations,
        target_45_fps_met=configurations[0]['capacity_fps']>=45,
        operational_sampler_unchanged=True)
    write_json(out/'inference_capacity.json',result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--duration',type=float,default=90)
    args=parser.parse_args()
    run(args.duration)
