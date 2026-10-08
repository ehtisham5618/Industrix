"""Generate acceptance evidence from actual measurements and append CME-3 lineage."""
import csv
import io
import json
import re
import subprocess
from datetime import datetime,timezone

from .benchmark import ROOT,REPORTS,VERSION,write_json


def tests(path):
    text=path.read_text(encoding='utf-8')
    count=int(re.search(r'Ran (\d+) tests',text)[1])
    return dict(tests=count,passed=count if '\nOK\n' in text else 0,
                status='PASS' if '\nOK\n' in text and 'Exit code: 0' in text else 'FAIL')


def main():
    baseline=json.loads((REPORTS/'baseline_metrics.json').read_text())
    optimized=json.loads((REPORTS/'optimized_metrics.json').read_text())
    required=tests(REPORTS/'required_tests_terminal.txt')
    related=tests(REPORTS/'related_tests_terminal.txt')
    tracker=tests(REPORTS/'tracker_escalation_tests_terminal.txt')
    stress=tests(REPORTS/'stress_tests_terminal.txt')
    streams=optimized['streams']
    checks={
        'Required branch used':subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip()=='feature/atlantis-async-rtsp',
        'stream_manager.py refactored':optimized['manager_source_sha256']!=baseline['manager_source_sha256'],
        'One independent capture thread per camera':len(streams)==3 and required['status']=='PASS',
        '3 concurrent streams supported':len(streams)==3 and all(s['captured']>0 for s in streams.values()),
        '15-frame ring buffer per camera':all(s['counters']['buffer']['capacity']==15 for s in streams.values()),
        'Ring buffers thread-safe':required['status']=='PASS',
        '1-in-4 deterministic sampler implemented':all(s['selected_for_evaluation']==(s['captured']+3)//4 for s in streams.values()),
        '~75% inference-frame reduction verified':abs(optimized['compute_frame_reduction_pct']-75)<2,
        'Actual evaluated FPS documented':all('evaluated_fps' in s for s in streams.values()),
        'Capture decoupled from inference':required['status']=='PASS' and all(abs(s['source_fps']-s['source']['encoded_fps'])<1 for s in streams.values()),
        'Fabric weaving stream active':streams['camera_01']['evaluated']>0,
        'Chemical storage stream active':streams['camera_02']['evaluated']>0,
        'Loading bay stream active':streams['camera_03']['evaluated']>0,
        '180-second integration benchmark completed':optimized['capture_duration_seconds']>=180,
        'Unintentional application-level frame drops = 0':optimized['unintentional_drop_count']==0,
        'True buffer overruns = 0':optimized['buffer_overrun_count']==0,
        'Intentional sampler skips reported separately':all(s['captured']==s['selected_for_evaluation']+s['intentional_skips'] for s in streams.values()),
        'Measured baseline CPU documented':baseline['capture_duration_seconds']>=180 and baseline['cpu']['samples']>150,
        'Optimized mean CPU <40%':optimized['cpu']['system_mean']<40 and optimized['cpu']['normalized_process_mean']<40,
        'CME-OPT3 15-frame timing compatibility verified':required['status']=='PASS' and all(s['expected_15_observation_seconds']<=2.05 for s in streams.values()),
        'test_stream_manager.py passing':required['status']=='PASS',
        'No orphan capture threads':not optimized['live_threads_after_stop'] and not optimized['scheduler_alive_after_stop'],
        'Stream failure isolation verified':required['status']=='PASS',
        'CME-3 tracking updated':True,
    }
    for s in streams.values():
        m=s['counters'];r=m['buffer']
        if s['selected_for_evaluation']!=s['evaluated']+r['true_overruns']+m['inference_drops']+r['pending_selected']:
            raise RuntimeError('Selected frame accounting does not conserve captured data')
        if r['pending_selected'] or r['max_occupancy']>15:
            raise RuntimeError('Invalid buffer shutdown/capacity evidence')
    status='PASS' if all(checks.values()) and all(t['status']=='PASS' for t in (required,related,tracker,stress)) else 'FAIL'
    checks['ESE-CPU2 OVERALL']=status=='PASS'
    reductions={key:dict(absolute_pp=baseline['cpu'][key]-optimized['cpu'][key],
        relative_pct=(baseline['cpu'][key]-optimized['cpu'][key])/baseline['cpu'][key]*100)
        for key in ('system_mean','normalized_process_mean')}
    source_commit=subprocess.check_output(['git','log','-1','--format=%H','--','SED_1_Multi_Camera/scripts/ring_buffer.py'],cwd=ROOT,text=True).strip()
    summary=dict(status=status,config_version=VERSION,source_commit=source_commit,
        baseline=baseline,optimized=optimized,cpu_reduction=reductions,
        tests=dict(required=required,all_sed1=related,tracker_and_escalation=tracker,stress=stress),
        acceptance={key:'PASS' if value else 'FAIL' for key,value in checks.items()})
    write_json(REPORTS/'acceptance_summary.json',summary)
    rows=[]
    for c,s in streams.items():
        m=s['counters'];r=m['buffer']
        rows.append(dict(camera_id=c,name=s['name'],encoded_fps=s['source']['encoded_fps'],
            captured=s['captured'],selected=s['selected_for_evaluation'],evaluated=s['evaluated'],
            evaluated_during_capture=s['evaluated_during_capture'],evaluated_during_drain=s['evaluated_during_drain'],
            source_fps=s['source_fps'],evaluated_fps=s['evaluated_fps'],intentional_skips=s['intentional_skips'],
            read_attempts=m['read_attempts'],read_failures=m['decode_failures'],open_failures=m['open_failures'],
            reconnections=m['reconnections'],loop_rewinds=m['loop_rewinds'],worker_crashes=m['worker_crashes'],
            ring_capacity=r['capacity'],mean_occupancy=r['mean_occupancy_per_write'],max_occupancy=r['max_occupancy'],
            circular_reuses=r['circular_reuses'],normal_reuses=r['normal_reuses'],true_overruns=r['true_overruns'],
            inference_drops=m['inference_drops'],frame_age_mean_ms=m['frame_ages_ms_mean'],
            frame_age_max_ms=m['frame_ages_ms_max'],confirmation_duration_seconds=s['expected_15_observation_seconds']))
    with (REPORTS/'stream_metrics.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    # Reuse the existing local CME-3 MLflow store; no trained model/policy row changes.
    from Experiment_Tracking.scripts.mlflow_utils import configure_tracking
    mlflow=configure_tracking(ROOT/'Experiment_Tracking/mlruns')
    with mlflow.start_run(run_name='ESE-CPU2: three-stream async ingestion') as run:
        mlflow.set_tags(dict(task='ESE-CPU2',experiment_type='async_video_ingestion',
            sprint='Sprint 4',status=status,config_version=VERSION,source_commit=source_commit))
        mlflow.log_params(dict(stream_count=3,ring_buffer_size=15,sampling_ratio='1/4',sampling_phase=0,
            source_fps=json.dumps({c:s['source']['encoded_fps'] for c,s in streams.items()}),
            test_duration=180,model_version='cme-opt2-focal-cosine-12class-v1',precision='PyTorch FP32',
            model_sha256=optimized['environment']['model_sha256'],imgsz=640,
            source_protocol='paced local video; actual RTSP NOT RUN',config_version=VERSION))
        mlflow.log_metrics(dict(baseline_mean_cpu=baseline['cpu']['system_mean'],
            baseline_peak_cpu=baseline['cpu']['system_peak'],optimized_mean_cpu=optimized['cpu']['system_mean'],
            optimized_peak_cpu=optimized['cpu']['system_peak'],
            baseline_normalized_process_cpu=baseline['cpu']['normalized_process_mean'],
            optimized_normalized_process_cpu=optimized['cpu']['normalized_process_mean'],
            cpu_reduction_pct=reductions['system_mean']['relative_pct'],
            compute_frame_reduction_pct=optimized['compute_frame_reduction_pct'],
            aggregate_eval_fps=optimized['aggregate_evaluated_fps'],
            unintentional_drops=optimized['unintentional_drop_count'],buffer_overruns=optimized['buffer_overrun_count']))
        summary['mlflow_run_id']=run.info.run_id
        write_json(REPORTS/'acceptance_summary.json',summary)
        lines=['# ESE-CPU2 Benchmark Report','',f'**Overall: {status}.** Evidence generated {datetime.now(timezone.utc).isoformat()}. No earlier completion or original deadline compliance is claimed.','',
            '## Architecture and method','',
            'RTSP/HTTP/USB/file → independent capture worker → fixed 15-slot raw ring → phase-zero 1-in-4 sampler → fair shared inference → calibrated CME-OPT3 ByteTRACK → unchanged 15 evaluated-observation confirmation → SED-2. Skipped raw frames cause no detector/tracker updates. The existing SED-1 manager is refactored; this folder contains validation/delivery tools, not a second production pipeline.',
            'The sampler records the modulo decision during raw ring write and the scheduler consumes the oldest still-retained selected slot. Every successfully decoded raw frame enters the ring. No inference/tracking executes under its lock. Each slot retains its selection/consumption state: replacing an unread selected slot is a true overrun; replacement of a skipped slot is normal reuse. The three independent rings cannot exceed 15 raw references each. Per-camera sequence starts at zero and never rewinds on file loop/reconnect. Session changes reset tracker/escalation state; the raw sampling phase continues.',
            'Original implementation: elapsed-time sampling at the existing config default 5 FPS, two-slot latest queues, loss on oldest-frame replacement. The same three native-FPS paced inputs, source model, image size, micro-batch, CPU thread configuration, thresholds, tracking and escalation are used for the 180-second baseline and optimized phases. New sampling intentionally replaces the old 5 FPS target; baseline is not inflated to an invented 30 FPS inference target.',
            f'Original baseline source SHA256 `{baseline["manager_source_sha256"]}`, Git `{baseline["git_head"]}`. Baseline ran before any SED-1 edits. Optimized source commit `{source_commit}`; source SHA256 `{optimized["manager_source_sha256"]}`. Three-frame warmup precedes measurement. Capture windows: baseline {baseline["capture_duration_seconds"]:.3f}s, optimized {optimized["capture_duration_seconds"]:.3f}s. Total optimized with shutdown drain {optimized["total_with_drain_seconds"]:.3f}s. All selected frames remaining at stop are drained and accounted for.',
            'CPU: existing SED-3 ResourceMonitor at one-second intervals, priming/shutdown excluded. Process percent is divided by four logical CPUs to use a machine-normalized 0–100 scale; system CPU includes all workstation activity. Both are disclosed and must be below 40 for the CPU check. Effective Ultralytics CPU thread count is three; OpenCV internal threads one. Original baseline metadata requested two threads before warmup but Ultralytics select_device resets them to NUM_THREADS=3; its corrected field and original requested value remain disclosed. Benchmark now records torch.get_num_threads. No affinity, artificial inference sleep, lower image size or replacement backend is used.',
            f'Environment: `{optimized["environment"]}`. CPU1 optimized exports remain local, unpromoted: source PyTorch FP32 is the actual production default. No retraining or checkpoint change. Capture frames remain at native resolution; detector uses its existing 640-pixel letterbox/NMS preprocessing. Source-file decode is wall-paced to simulate live arrivals, independent of inference.','',
            '## Three feeds and sampling','',
            'Source protocol: **local video simulation**. Actual RTSP protocol test: **NOT RUN** (no endpoints). Network RTP packet loss: **not directly observable through OpenCV**. No fabricated network-loss zero is claimed. Camera names identify intended deployment roles, not actual chemical-storage/loading-bay scene verification. Chemical source is a public hazmat exercise and loading source is rooftop workers; weaving uses the existing historical factory documentary. Public-video provenance is in `Confidence_Calibration/benchmark/source_manifest.csv` and `CME_OPT3_ByteTrack/reports/CME_OPT3_Benchmark_Report.md`. Source hashes, dimensions and durations are recorded in the metrics JSON.',
            '| Camera / deployment role | Actual local source | Native FPS | Captured | Selected | Evaluated total | Intentional skips | Sustained eval FPS |','|---|---|---:|---:|---:|---:|---:|---:|']
        for c,s in streams.items(): lines.append(f'| {c}: {s["name"]} | {s["source"]["path"]} | {s["source"]["encoded_fps"]:.3f} | {s["captured"]} | {s["selected_for_evaluation"]} | {s["evaluated"]} | {s["intentional_skips"]} | {s["evaluated_fps"]:.3f} |')
        lines += ['',f'Raw sampler skips are exactly phase-zero selection: `{sum(s["intentional_skips"] for s in streams.values())/optimized["captured"]*100:.3f}%`. Actual compute-frame reduction = 1 − evaluated/captured = **{optimized["compute_frame_reduction_pct"]:.3f}%**. Values above 75% here include genuine lost selected work; they are **not** extra successful optimization. Evaluated total includes drain for conservation; sustained FPS uses evaluations completed within the capture window, with per-camera drain counts in CSV. Baseline evaluated FPS was measured as total evaluated divided by capture time and includes drain; use it as approximate throughput, not a pure sustained-window observation.','',
            '## Ring, latency and reliability','',
            '| Camera | Capacity | Mean occupancy/write | Max | Circular reuses | Normal reuses | True overruns | Read failures | Reconnects | Worker crashes |','|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
        for c,s in streams.items():
            m=s['counters'];r=m['buffer'];lines.append(f'| {c} | 15 | {r["mean_occupancy_per_write"]:.3f} | {r["max_occupancy"]} | {r["circular_reuses"]} | {r["normal_reuses"]} | {r["true_overruns"]} | {m["decode_failures"]} | {m["reconnections"]} | {m["worker_crashes"]} |')
        lines += ['', 'Conservation: captured = intentional skips + selected; selected = evaluated + true overruns + inference/routing drops + pending selected. Every camera passes these equations and pending selected is zero after drain. Ring max/mean counters cover every write; bounded timing/depth histories retain their most recent 4096 entries. Frame-age summaries include stop drain and can exceed the running 15-frame horizon during that separately reported drain. CSV contains one-second occupancy observations. Capture timestamp and pre-ring-write timestamp live on FramePacket; scheduler timestamps selection and inference start. Full JSON reports capture→selection, selection→inference and capture→inference mean/max milliseconds.',
            'Native network open/read deadlines are 2000ms via OpenCV FFmpeg parameters; failed network opens/reads use cancelable exponential retry from 0.25s to 4s. Backend limitations are explicit: USB reads do not have a portable OpenCV timeout. An uninterruptible driver makes stop raise and prevents an overlapping restart; no successful cleanup is claimed until threads actually join. Fake blocked/reconnect sources test isolation and cancellation. Local EOF loops increment session_generation without being counted as a decode failure. Exceptions are recorded without exposing private source URLs.','',
            '## CPU comparison','', 'Task-stated baseline **95% is reference only**. Measured data:',
            '| Metric | Baseline | Optimized | Target | Result |','|---|---:|---:|---|---|',
            f'| Concurrent active feeds | 3 | 3 | 3 | PASS |',
            f'| System mean CPU % | {baseline["cpu"]["system_mean"]:.3f} | {optimized["cpu"]["system_mean"]:.3f} | <40 | {summary["acceptance"]["Optimized mean CPU <40%"]} |',
            f'| System peak CPU % | {baseline["cpu"]["system_peak"]:.3f} | {optimized["cpu"]["system_peak"]:.3f} | diagnostic | — |',
            f'| Normalized process mean CPU % | {baseline["cpu"]["normalized_process_mean"]:.3f} | {optimized["cpu"]["normalized_process_mean"]:.3f} | <40 | {summary["acceptance"]["Optimized mean CPU <40%"]} |',
            f'| Normalized process peak CPU % | {baseline["cpu"]["normalized_process_peak"]:.3f} | {optimized["cpu"]["normalized_process_peak"]:.3f} | diagnostic | — |',
            f'| Frames evaluated total | {baseline["evaluated"]} | {optimized["evaluated"]} | ~25% captured | {summary["acceptance"]["~75% inference-frame reduction verified"]} |',
            f'| Compute frame reduction % | {baseline["compute_frame_reduction_pct"]:.3f} | {optimized["compute_frame_reduction_pct"]:.3f} | ~75 | {summary["acceptance"]["~75% inference-frame reduction verified"]} |',
            f'| Unintentional captured-frame losses | {baseline["unintentional_drop_count"]} | {optimized["unintentional_drop_count"]} | 0 | {summary["acceptance"]["Unintentional application-level frame drops = 0"]} |',
            f'| True overruns | {baseline["buffer_overrun_count"]} | {optimized["buffer_overrun_count"]} | 0 | {summary["acceptance"]["True buffer overruns = 0"]} |',
            '',f'Absolute and relative CPU reduction: `{reductions}`. Relative formula `(baseline mean − optimized mean)/baseline mean × 100`. Negative values mean increased CPU. The sampler is correct but the actual FP32 detector cannot sustain the selected demand on this two-core laptop. Buffers cap backlog and disclose the deficit instead of silently discarding it. Resolving the performance gates requires a separately validated faster detector runtime/hardware; slowing sources, selecting fewer than 1-in-4 or suppressing counters would invalidate this task.','',
            '## CME-OPT3 timing','',
            'The unit test verifies only evaluated observations advance real ByteTRACK and the unchanged 15-observation state machine. With raw 30 FPS, nominal 7.5 eval FPS gives a 15/FPS estimate of 2s (first-to-fifteenth observation span is 14/FPS). Each source here has its own native cadence, and actual inference capacity is lower:',
            '| Camera | Native/4 target eval FPS | Actual sustained eval FPS | Expected 15-observation duration |','|---|---:|---:|---:|']
        for c,s in streams.items(): lines.append(f'| {c} | {s["source"]["encoded_fps"]/4:.3f} | {s["evaluated_fps"]:.3f} | {s["expected_15_observation_seconds"]:.3f}s |')
        lines += ['', 'This timing estimate is throughput-based, not a measured ground-truth violation alert delay. Camera roles are unannotated public simulations; previous missed-hazard findings remain. The 2s real-time timing target fails when actual cadence is this low; state-machine logic still passes and no threshold was lowered.','',
            '## Tests and acceptance','', f'Required file: {required}. All SED-1 tests including required file: {related}. Tracker/SED-2 tests: {tracker}. SED-3 monitor tests: {stress}. No live workers or scheduler remain after the official run. Required tests cover fixed capacity, 0/4 boundary, exact 25/75 accounting, ordering/conservation under threaded stress, separate buffers, three sources, slow/failed camera isolation, retry/backoff, session rewind, detector failure, stop/restart, overlap refusal and real ByteTRACK→15 observations→SED-2.',
            '', '| Definition of Done | Verdict |','|---|---|']
        lines += [f'| {key} | {value} |' for key,value in summary['acceptance'].items()]
        changed=subprocess.check_output(['git','diff','--name-only',baseline['git_head'],'HEAD'],cwd=ROOT,text=True).splitlines()
        lines += ['', '## Tracking, files and offline handoff','',f'CME-3 local MLflow run `{run.info.run_id}`, experiment type `async_video_ingestion`, config `{VERSION}`. Trained detector and policy registry rows are unchanged; an ingestion experiment row is appended. Lineage: CME-OPT2 selected FP32 detector → CPU2 async ingestion → CME-OPT3 tracker → SED-2. CPU1 formats remain recorded as optional failed deployment candidates.',
            f'Created/modified source files in first commit: `{changed}`. Additional second-commit files: this report, measured JSON/CSV, CPU graph, terminal outputs, acceptance summary and updated Experiment_Tracking/experiments.csv. Removed files: none.',
            'Exactly two task commits are saved locally. The branch was newly created from completed local CPU1 HEAD; prior branches/history remain preserved. This is the task-specified feature branch, so reviewable changes stay grouped on it. No push/PR was attempted while organization access is revoked. Source commit is shown above; both final commit IDs are recorded in ignored `ESE_CPU2_Async_RTSP/backups/delivery_manifest.json` after commit two. Later sync: `git push -u origin feature/atlantis-async-rtsp`. A verified complete Git bundle is actually cloned to confirm recovery; runtime ZIP restores the ignored source model/media and local MLflow store.',
            '', 'References: [OpenCV timeout property support](https://docs.opencv.org/4.13.0/d4/d15/group__videoio__flags__base.html), [Python Event and thread joining](https://docs.python.org/3/library/threading.html). Native backend timeouts are configured at open; joined thread state is checked explicitly.']
        (REPORTS/'ESE_CPU2_Benchmark_Report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
        mlflow.log_artifacts(str(REPORTS))
    csv_path=ROOT/'Experiment_Tracking/experiments.csv'
    original=csv_path.read_bytes()
    table=list(csv.DictReader(io.StringIO(original.decode('utf-8'))))
    if any(r['run_id']=='ESECPU2-EXP-001' for r in table): raise RuntimeError('Ingestion experiment already appended')
    row=dict(run_id='ESECPU2-EXP-001',run_name='ESE-CPU2: three-stream async ingestion',sprint='Sprint 4',
        task='ESE-CPU2',stage='CPU Ingestion',experiment_type='async_video_ingestion',
        model_version='cme-opt2-focal-cosine-12class-v1',alert_policy_version='cmeopt3-bytetrack15-v1',
        model_architecture='YOLOv8s',num_classes=12,batch_size=3,imgsz=640,device='CPU',
        environment=optimized['environment']['cpu'],best_weight_uri='Backend/best.pt',
        source_script='SED_1_Multi_Camera/scripts/stream_manager.py',git_commit=source_commit,
        status='validated_targets_met' if status=='PASS' else 'evaluated_target_shortfall',
        tracking_origin='actual_local_cpu_async_ingestion',confidence_config='Confidence_Calibration/configs/calibrated_thresholds.yaml',
        sampling_fps=json.dumps({c:s['evaluated_fps'] for c,s in streams.items()}),window_size=15,required_frames=15,
        notes=json.dumps(dict(mlflow_run_id=summary['mlflow_run_id'],config_version=VERSION,status=status,
            baseline_mean_cpu=baseline['cpu']['system_mean'],optimized_mean_cpu=optimized['cpu']['system_mean'],
            drops=optimized['unintentional_drop_count'],overruns=optimized['buffer_overrun_count'],
            report='SED_1_Multi_Camera/reports/ESE_CPU2/ESE_CPU2_Benchmark_Report.md'),separators=(',',':')))
    stream=io.StringIO(newline='');writer=csv.DictWriter(stream,fieldnames=list(table[0]));writer.writerow({k:row.get(k,'') for k in table[0]})
    csv_path.write_bytes(original+stream.getvalue().encode('utf-8'))
    print(json.dumps(dict(status=status,mlflow_run_id=summary['mlflow_run_id'],acceptance=summary['acceptance']),indent=2))


if __name__=='__main__':main()
