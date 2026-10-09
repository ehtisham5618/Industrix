"""Current hardware/IR measurements and unchanged legacy acceptance gates."""
from pathlib import Path
import hashlib
import json
import statistics
import time
import zlib

ROOT=Path(__file__).resolve().parents[1]

def main():
    import cv2,numpy as np,openvino as ov,psutil
    cv2.setNumThreads(1)
    from ESE_CPU1_Quantization.common import preprocess
    directory=ROOT/'Backend/weights/openvino_int8'
    graph=ov.Core().read_model(directory/'model.xml')
    constants={}
    for op in graph.get_ops():
        if op.get_type_name()=='Constant':
            kind=str(op.get_element_type());constants[kind]=constants.get(kind,0)+op.data.nbytes
    data=directory.joinpath('model.bin').read_bytes()
    compiled=ov.Core().compile_model(graph,'CPU',{'PERFORMANCE_HINT':'LATENCY','INFERENCE_NUM_THREADS':2,'NUM_STREAMS':1})
    paths=[ROOT/'Hazard_Expansion/content_runtime/combined_dataset_augmented_v3'/p for p in
        (ROOT/'ESE_CPU1_Quantization/runtime/calibration_images.txt').read_text().splitlines()[:5]]
    paths=[p if p.is_file() else Path(str(p).split('combined_dataset_augmented_v3')[-1].lstrip('/\\')) for p in paths]
    # The calibration file actually stores absolute paths; Path joins preserve those.
    frames=[preprocess(cv2.imread(str(p))) for p in paths]
    assert len(frames)==5 and all(x.shape==(1,3,640,640) for x in frames)
    for i in range(30):compiled([frames[i%5]])
    latencies=[]
    for i in range(200):
        started=time.perf_counter();output=compiled([frames[i%5]])[compiled.output(0)]
        latencies.append((time.perf_counter()-started)*1000)
        assert output.shape==(1,16,8400) and np.isfinite(output).all()
    old=json.loads((ROOT/'SED_3_Stress_Testing/reports/quant_report.json').read_text())
    candidate=json.loads((ROOT/'reports/qci3/cpu_bias_candidate.json').read_text())
    size=sum((directory/n).stat().st_size for n in ('model.xml','model.bin'))
    mean=statistics.mean(latencies);drop=(old['accuracy']['fp32']['map50']-old['accuracy']['int8']['map50'])*100
    result={'dataset_permission':{'status':'PASS','scope':'user-confirmed noncommercial research and evaluation',
        'source':'https://www.vicos.si/resources/kolektorsdd/','license':'CC BY-NC-SA 4.0','commercial_permission_required_for_current_scope':False},
        'current_ir_bytes':size,'size_limit_bytes':6500000,'size_pass':size<6500000,
        'constant_bytes_by_type':constants,'dense_INT8_constant_bytes':constants.get("<Type: 'int8_t'>",0),
        'dense_IR_size_constraint':'Unchanged dense YOLOv8s INT8 constants alone exceed 6.5 MB; graph/API optimizations cannot remove those stored weights.',
        'zlib9_bin_plus_xml_bytes':len(zlib.compress(data,9))+(directory/'model.xml').stat().st_size,
        'nncf_int4_request_actual_candidate_bytes':11757999,
        'nncf_int4_request_actual_result':'Installed NNCF 3.4 kept all 64 convolution weight groups at INT8; no true INT4 candidate or deployment claimed.',
        'full_bias_candidate':candidate,'candidate_deployed':False,
        'current_recorded_test_map_drop_pp':drop,'accuracy_0_8pp_pass':drop<.8,'accuracy_1pp_pass':drop<1,
        'warmups':30,'timed_iterations':200,'input_shape':[1,3,640,640],'physical_cores':psutil.cpu_count(logical=False),
        'device':'CPU','threads':2,'streams':1,'measurement':'existing IR actual inference only; decoding/preprocessing/NMS excluded',
        'mean_ms':mean,'p95_ms':sorted(latencies)[189],'max_ms':max(latencies),'model_inference_under_20ms_pass':mean<20,
        'serial_inference_capacity_fps':1000/mean,'three_stream_requested_total_fps':48,
        'three_stream_sustainable_on_this_serial_model':1000/mean>=48,
        'raw_latencies_ms':latencies,'xml_sha256':hashlib.sha256((directory/'model.xml').read_bytes()).hexdigest(),
        'bin_sha256':hashlib.sha256(data).hexdigest(),'gpu_started':False,
        'scope_preserved':'No smaller retrained model silently substituted, no test set used for candidate selection, no acceptance threshold/test suppressed.',
        'required_remaining_change':'A smaller/pruned retrained detector or a different precision contract is needed for size; measured target hardware is needed for CPU throughput. This is not a claim that those alternatives have passed.'}
    path=ROOT/'reports/qci3/cpu_acceptance_followup.json';path.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('current_ir_bytes','dense_INT8_constant_bytes','size_pass','current_recorded_test_map_drop_pp','mean_ms','model_inference_under_20ms_pass','serial_inference_capacity_fps')}),flush=True)

if __name__=='__main__':main()
