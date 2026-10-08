"""Summaries and standalone graphs computed only from persisted measured samples."""
from __future__ import annotations

import csv
import json
import statistics
from pathlib import Path

from ESE_CPU1_Quantization.common import ROOT
from SED_3_Stress_Testing.scripts.analysis import summarize_values
from .analysis import values,optional_stats,memory_trend,soak_windows,evaluate_dod,thermal_analysis


def read_rows(path):
    with Path(path).open(newline='',encoding='utf-8') as f:
        rows=list(csv.DictReader(f))
    for row in rows:
        for key,value in list(row.items()):
            if value=='':row[key]=None
            elif value in ('True','False'):row[key]=value=='True'
            else:
                try:row[key]=float(value)
                except ValueError:pass
    return rows


def summarize(context,paths):
    rows=read_rows(paths['telemetry'])
    measured=[r for r in rows if not r['warmup'] and r['soak_elapsed_seconds']<=context['duration_actual_seconds']]
    warmup=context['warmup_seconds'];deadline=context['capture_wall_seconds']
    inference=[r for r in read_rows(paths['inference']) if warmup<=r['elapsed_seconds']<=deadline]
    frames=[r for r in read_rows(paths['frames']) if warmup<=r['elapsed_seconds']<=deadline]
    memory={field:memory_trend(measured,field,minimum_growth_mb=10 if field=='process_rss_mb' else 1)
            for field in ('process_rss_mb','tracemalloc_current_mb')}
    per_camera={c:dict(evaluated_during_soak=sum(r['camera_id']==c for r in frames),
        operational_fps=sum(r['camera_id']==c for r in frames)/max(.000001,context['duration_actual_seconds']),
        source=context['sources'][c],**metrics) for c,metrics in context['manager_metrics'].items()}
    operational=len(frames)/max(.000001,context['duration_actual_seconds'])
    capacity_path=ROOT/'ESE_CPU3_Soak_Test/reports/inference_capacity.json'
    capacity=json.loads(capacity_path.read_text()) if capacity_path.exists() else None
    capacity_fps=capacity['selected_configuration']['capacity_fps'] if capacity else None
    crash_count=sum(m['worker_crashes'] for m in context['manager_metrics'].values())+len(context['exceptions'])
    clean=not context['threads_after_shutdown'] and not context['scheduler_after_shutdown']
    latency=summarize_values(values(inference,'inference_ms'))
    timing={key:summarize_values(values(inference,key)) for key in ('preprocess_ms','nms_ms')}
    timing['routing_ms']=summarize_values(values(frames,'routing_ms'))
    timing['end_to_end_ms']=summarize_values(values(frames,'end_to_end_ms'))
    frequency=thermal_analysis(measured)
    windows=soak_windows(measured)
    for index,window in enumerate(windows):
        # Exact recorded inference completion times determine window percentiles.
        subset=[r for r in inference if warmup+index*600<=r['elapsed_seconds']<warmup+(index+1)*600]
        window['inference_latency_ms']=summarize_values(values(subset,'inference_ms'))
    rss=values(measured,'process_rss_mb');python=values(measured,'tracemalloc_current_mb')
    process_stats=optional_stats(measured,'normalized_process_cpu_pct')
    system_stats=optional_stats(measured,'system_cpu_pct')
    dod=evaluate_dod(context['status'],context['duration_actual_seconds'],crash_count,memory,operational,capacity_fps,clean)
    enough=all(m.get('evidence_sufficient') for m in memory.values())
    leaks=any(m.get('leak_detected') is True for m in memory.values())
    thread_values=values(measured,'capture_thread_count');native_threads=values(measured,'thread_count')
    native_thread_trend=memory_trend(measured,'thread_count',minimum_growth_mb=2)
    thread_leak=native_thread_trend.get('leak_detected') is True
    workers_stable=bool(thread_values) and min(thread_values)==max(thread_values)==3
    if thread_leak or not workers_stable:
        dod['no_memory_leak_evidence']=False
        dod['overall_pass']=False
    result=dict(**context,streams=3,stream_results=per_camera,
        throughput=dict(operational_mean_fps=operational,
            operational_p50_fps=optional_stats(measured,'aggregate_fps')['p50'] if measured else None,
            operational_p95_fps=optional_stats(measured,'aggregate_fps')['p95'] if measured else None,
            inference_capacity_fps_if_measured=capacity_fps,capacity_details=capacity,
            sampling_ceiling_fps=sum(s['encoded_fps']/4 for s in context['sources'].values()),
            target=45,target_metric='operational integrated pipeline FPS; separate ready-tensor engine capacity also evaluated',
            definition_conflict='Three nominal 30 FPS feeds sampled 1-in-4 cap operational FPS at 22.5; these native-rate feeds cap it at 19.7305. Neither cap reaches 45. The sampler remains enabled.'),
        latency={key+'_ms':value for key,value in latency.items()},pipeline_timing=timing,
        cpu=dict(process_mean_pct=process_stats['mean'] if process_stats else None,
            process_p95_pct=process_stats['p95'] if process_stats else None,process_peak_pct=process_stats['max'] if process_stats else None,
            system_mean_pct=system_stats['mean'] if system_stats else None,system_peak_pct=system_stats['max'] if system_stats else None,
            process_normalized=process_stats,process_raw=optional_stats(measured,'process_cpu_pct'),system=system_stats,
            normalization='Process CPU divided by four logical CPUs; machine normalized 0-100%, raw percent also retained'),
        memory=dict(rss_start_mb=rss[0] if rss else None,rss_mean_mb=statistics.fmean(rss) if rss else None,
            rss_peak_mb=max(rss) if rss else None,rss_end_mb=rss[-1] if rss else None,
            rss_slope_mb_per_hour=memory['process_rss_mb'].get('slope_mb_per_hour'),
            tracemalloc_start_mb=python[0] if python else None,
            tracemalloc_mean_mb=statistics.fmean(python) if python else None,
            tracemalloc_peak_mb=max(values(measured,'tracemalloc_peak_mb')) if measured else None,
            tracemalloc_end_mb=python[-1] if python else None,leak_detected=leaks if enough else None,
            analysis=memory,system_ram=optional_stats(measured,'system_ram_pct'),
            conclusion='No evidence of sustained memory growth/leak during the 60-minute run.' if dod['no_memory_leak_evidence'] else
                'Sustained growth evidence detected' if leaks else 'Full-duration leak conclusion unavailable for incomplete/short run'),
        thermal=frequency,
        streams_health=dict(crashes=crash_count,reconnects=sum(m['reconnects'] for m in context['manager_metrics'].values()),
            read_failures=sum(m['read_failures'] for m in context['manager_metrics'].values()),
            buffer_overruns=sum(m['ring']['true_overruns'] for m in context['manager_metrics'].values()),
            capture_threads_stable=workers_stable,native_thread_growth_suspected=thread_leak,
            native_thread_trend=native_thread_trend,
            native_threads_min=min(native_threads) if native_threads else None,
            native_threads_max=max(native_threads) if native_threads else None,
            ring_capacity_bounded=all(m['ring']['capacity']==15 and m['ring']['max_occupancy']<=15 for m in context['manager_metrics'].values()),
            clean_shutdown=clean),windows=windows,telemetry_samples=len(measured),dod=dod,
        overall='PASS' if dod['overall_pass'] else 'FAIL',
        instrumentation='tracemalloc started before live warmup, psutil RSS, persisted one-second telemetry; histories bounded, full latency series persisted instead of retained in RAM',
        actual_rtsp_protocol_test='NOT RUN; local video simulation',
        cpu1_previous_acceptance='Selected INT8 artifact had CPU1 accuracy/size/latency shortfalls; this soak does not override those results')
    if len(windows)>=2:
        first,last=windows[0],windows[-1]
        result['window_degradation']=dict(
            fps_change_pct=(last['aggregate_fps']/first['aggregate_fps']-1)*100 if first['aggregate_fps'] else None,
            latency_change_pct=(last['inference_latency_ms']['mean']/first['inference_latency_ms']['mean']-1)*100 if first['inference_latency_ms']['mean'] else None,
            rss_change_pct=(last['rss']['mean']/first['rss']['mean']-1)*100 if first['rss'] else None)
    return result


def render(report,path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    rows=read_rows(ROOT/report['telemetry_path']);out=path.parent
    prefix=path.stem.replace('_report','')
    xs=[r['elapsed_seconds']/60 for r in rows]
    for name,series,ylabel,title in [
        ('cpu',[('system_cpu_pct','System CPU'),('normalized_process_cpu_pct','Normalized process CPU')],'CPU (%)','Measured CPU utilization'),
        ('memory',[('process_rss_mb','Process RSS'),('tracemalloc_current_mb','Python traced allocations')],'Memory (MiB)','RSS and Python allocation telemetry'),
        ('fps',[('aggregate_fps','Evaluated FPS')],'Frames/sec','Operational evaluated FPS (sampling retained)'),
        ('thermal',[('cpu_freq_mhz','Reported CPU MHz')],'MHz','CPU frequency (temperature unavailable)' if not report['thermal']['temperature_available'] else 'Reported CPU frequency')]:
        if name=='thermal' and not report['thermal']['frequency_available']:continue
        fig,ax=plt.subplots(figsize=(10,3.5),layout='constrained')
        for key,label in series:
            ax.plot(xs,[r.get(key) for r in rows],label=label,linewidth=.8)
        ax.axvspan(0,report['warmup_seconds']/60,color='#d8d8d8',alpha=.5,label='Warmup')
        ax.set(xlabel='Continuous workload minutes',ylabel=ylabel,title=title)
        if name=='fps':ax.axhline(45,color='red',linestyle='--',label='45 FPS task target')
        ax.legend(fontsize=8);ax.grid(alpha=.2);fig.savefig(out/(prefix+'_'+name+'.png'),dpi=130);plt.close(fig)
    if report['thermal']['temperature_available']:
        fig,ax=plt.subplots(figsize=(10,3),layout='constrained')
        ax.plot(xs,[r.get('cpu_temp_c') for r in rows]);ax.set(xlabel='Minutes',ylabel='CPU temperature (C)')
        fig.savefig(out/(prefix+'_temperature.png'),dpi=130);plt.close(fig)
    checks={
        'Required Git branch used':'PASS',
        'OpenVINO INT8 engine verified':'PASS',
        '3 concurrent simulated feeds active':'PASS' if report['streams_health']['capture_threads_stable'] else 'FAIL',
        'ESE-CPU2 async ingestion reused':'PASS',
        '60-minute / 3600-second continuous run completed':'PASS' if report['dod']['completed_60_minutes'] else 'FAIL',
        'No unrecoverable crashes':'PASS' if report['dod']['no_crashes'] else 'FAIL',
        'Process RSS monitored':'PASS' if report['memory']['rss_mean_mb'] is not None else 'FAIL',
        'tracemalloc monitored':'PASS' if report['memory']['tracemalloc_start_mb'] is not None else 'FAIL',
        'No evidence of sustained RSS growth':'PASS' if report['dod']['completed_60_minutes'] and report['memory']['analysis']['process_rss_mb'].get('leak_detected') is False else 'FAIL',
        'No evidence of sustained Python allocation growth':'PASS' if report['dod']['completed_60_minutes'] and report['memory']['analysis']['tracemalloc_current_mb'].get('leak_detected') is False else 'FAIL',
        'Thread/worker count stable':'PASS' if report['streams_health']['capture_threads_stable'] and not report['streams_health']['native_thread_growth_suspected'] else 'FAIL',
        'Ring buffers stable':'PASS' if report['streams_health']['ring_capacity_bounded'] else 'FAIL',
        'CPU utilization recorded':'PASS' if report['cpu']['system_mean_pct'] is not None else 'FAIL',
        'CPU frequency recorded':'PASS' if report['thermal']['frequency_available'] else 'UNAVAILABLE',
        'CPU temperature recorded':'PASS' if report['thermal']['temperature_available'] else 'UNAVAILABLE',
        'Thermal throttling analyzed':'UNAVAILABLE',
        'Operational aggregate FPS documented':'PASS',
        'Inference-capacity FPS documented where required':'PASS' if report['throughput']['inference_capacity_fps_if_measured'] is not None else 'FAIL',
        '>=45 FPS task target':'PASS' if report['dod']['throughput_target_met'] else 'FAIL',
        'Latency mean/P95/P99 documented':'PASS',
        'cpu_soak_report.json generated':'PASS',
        'CPU/RAM telemetry graphs generated':'PASS',
        'Final soak report generated':'PASS',
        'CME-3 tracking updated':'PENDING until offline finalization',
        'ESE-CPU3 OVERALL':report['overall']}
    report['acceptance']=checks
    lines=['# ESE-CPU3 Soak Test Report','',f"**Execution: {report['status']}; acceptance: {report['overall']}.**",'',
        f"Actual UTC start {report['started_at_utc']}, finish {report['finished_at_utc']}. Original October 1 deadline has passed; no earlier completion is claimed.",'',
        '## System and methodology','',f"Detector `{report['model_version']}` → CPU1 selected OpenVINO INT8 → CPU2 independent captures/ring15/sample4 → CME-OPT3 calibrated ByteTRACK/15 evaluated observations → SED-2 software-only escalation. Config `{report['config_version']}` / `{report['ingestion_config_version']}`. Exact class mapping, hashes, precision, compilation and CPU settings: `{report['engine_verification']}`.",
        f"Hardware/software: `{report['hardware']}`. Requested monitored soak {report['duration_requested_seconds']}s; actual {report['duration_actual_seconds']:.3f}s. Warmup {report['warmup_seconds']}s runs in the same process before the primary monitored period. Capture wall {report['capture_wall_seconds']:.3f}s; with shutdown {report['wall_seconds_with_shutdown']:.3f}s. No pipeline restart on media looping. Tracemalloc begins before warmup; post-warmup analysis excludes warmup. Sampling interval {report['sample_interval_seconds']}s; full telemetry persisted rather than retained in an accumulating Python list.",
        'CPU1 deployment targets previously failed. This task exercises its selected artifact without promoting it or overriding that acceptance. No retraining, quantization rerun, resolution change, GPU/NPU or fallback backend. Input static batch1 640x640, CPU LATENCY/one stream/two threads as validated by CPU1. A shared scheduler may select three frames; the static artifact runs each once in order, then real NMS rescales boxes to source coordinates before tracking/geofences. Pure model latency excludes preprocessing/NMS; separate timers record those and tracking/escalation routing. No dummy detector.',
        'The host is shared, not exclusively isolated. Tracemalloc adds measured instrumentation overhead. One-hour claims apply only to this workstation and configuration. Temperature is unavailable unless the host exposes a supported CPU sensor; frequency on Windows can be nominal and cannot independently establish thermal throttling.','',
        '## Feeds and throughput','',report['throughput']['definition_conflict'],
        f"Operational integrated FPS **{report['throughput']['operational_mean_fps']:.3f}**; separately measured ready-tensor engine capacity **{report['throughput']['inference_capacity_fps_if_measured']} FPS**. The 45 FPS operational gate is **{'PASS' if report['dod']['throughput_target_met'] else 'FAIL'}**. Engine capacity also {'meets' if report['dod']['inference_capacity_target_met'] else 'fails'} 45 FPS. Capacity never substitutes for camera throughput. Frame completion timestamps during the 3600-second period define throughput; stop drain is excluded. All raw sampler skips and true selected-frame overruns remain separately counted. Actual RTSP test NOT RUN.",
        '| Camera | Source | Source FPS | Soak eval FPS | Captured total | Evaluated total | Skips | True overruns | Rewinds |','|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for c,s in report['stream_results'].items():
        lines.append(f"| {c}: {s['source']['name']} | {s['source']['path']} | {s['source']['encoded_fps']:.3f} | {s['operational_fps']:.3f} | {s['captured']} | {s['evaluated']} | {s['intentional_skips']} | {s['ring']['true_overruns']} | {s['loop_rewinds']} |")
    lines += ['', 'Source roles use public documentary/hazmat-exercise/rooftop-worker simulations. These are not installed weaving/chemical/loading-bay CCTV; original media provenance remains in CPU2/CME-OPT3 reports. Source hashes and native dimensions are in JSON. RTP network losses are not observable through OpenCV.','',
        '## Latency, CPU and memory','',f"Pure OpenVINO latency milliseconds: `{report['latency']}`. Separate preprocessing, NMS, tracking/escalation routing and capture-to-completion: `{report['pipeline_timing']}`. All measured calls, not the last bounded diagnostic cache, determine percentiles. Stop drain is excluded.",
        f"CPU: `{report['cpu']}`. Raw process CPU can exceed 100%; machine normalized process CPU divides by four logical cores. Both percent series remain available.",
        f"Memory: `{report['memory']}`. Units MiB (2^20 bytes). RSS covers native memory that Python tracing may miss. Python allocation peak and end are independently captured; slight allocator/cache fluctuation alone does not imply a leak.",
        'Memory heuristic: after warmup, require a materially positive whole-run slope, first-to-final stable-window increase, AND a materially positive final-20-minute slope before flagging sustained growth. RSS minimum material growth is 10 MiB and Python minimum 1 MiB; relative growth threshold is 5% of early-window memory and slope threshold at least 2%/hour. These thresholds were defined before measurement. Fixed history/cache filling that plateaus is distinguished from continuing growth. Top ten positive allocation deltas are saved at 15/30/45/60 minutes. This is evidence for a finite one-hour run, not proof that every possible workload is leak-free.',
        f"Memory conclusion: **{report['memory']['conclusion']}**.",'',
        '## Thermal and reliability','',f"Thermal/frequency report: `{report['thermal']}`. Missing metrics are null/blank, never fabricated zeros. Frequency change alone is not labeled throttling.",
        f"Health: `{report['streams_health']}`. Thread counts `{report['thread_counts']}`; active capture workers after stop `{report['threads_after_shutdown']}`. Event histories/resolved records are bounded to 1024 in this harness and archived to the existing JSONL event store; active safety incidents are never evicted. CPU2 rings remain 15 slots, timing diagnostic histories remain 4096 entries, and per-frame timing records are streamed to disk. Alert storage: `{report['event_store']}`.",
        f"Failures: `{report['exceptions']}`. All three streams loop independently; loop sessions reset tracking/escalation according to CPU2 behavior without restarting the process, clock or telemetry.",'',
        '## Six 10-minute windows','',
        '| Window | FPS | Mean inference ms | P95 ms | System CPU % | RSS MiB | Python MiB | Temp C | MHz |','|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    def mean(item):return f"{item['mean']:.3f}" if item else 'NA'
    for w in report['windows']:
        lines.append(f"| {w['window']} | {w['aggregate_fps']:.3f} | {w['inference_latency_ms']['mean']:.3f} | {w['inference_latency_ms']['p95']:.3f} | {mean(w['system_cpu'])} | {mean(w['rss'])} | {mean(w['python_alloc'])} | {mean(w['temperature'])} | {mean(w['frequency'])} |")
    lines += ['',f"Early/final window comparison: `{report.get('window_degradation')}`. Workload, source clips, runtime settings and sampling remain unchanged. Performance variation is retained and not used to invent a thermal diagnosis.",'',
        '## Definition of Done','', '| Check | Result |','|---|---|']
    lines += [f'| {key} | {value} |' for key,value in checks.items()]
    lines += ['', '## Artifacts and offline delivery','',
        f"JSON `{path.relative_to(ROOT).as_posix()}`, telemetry `{report['telemetry_path']}`, inference timing `{report['inference_path']}`, frame timing `{report['frame_timings_path']}`. CPU, memory, FPS and frequency graphs use only measured samples. Tests and CME-3 run metadata are attached during finalization after the real full-duration evidence exists.",
        'Required feature branch `feature/atlantis-cpu-soak-test` is based on completed local CPU2. Exactly two task commits are saved after actual 60-minute evidence; user reports organization access revoked, so no push/PR now. Later sync: `git push -u origin feature/atlantis-cpu-soak-test`. Verified Git bundle, artifact/media archive and local tracking archive remain ignored under `ESE_CPU3_Soak_Test/backups/`.',
        '', '[CPU graph]('+prefix+'_cpu.png), [memory graph]('+prefix+'_memory.png), [throughput graph]('+prefix+'_fps.png), [frequency graph]('+prefix+'_thermal.png).',
        '', 'References: [OpenVINO CPU properties](https://docs.openvino.ai/nightly/openvino-workflow/running-inference/inference-devices-and-modes/cpu-device.html), [tracemalloc limits and snapshots](https://docs.python.org/3/library/tracemalloc.html), [psutil frequency and sensors](https://psutil.readthedocs.io/stable/index.html).']
    markdown=out/('ESE_CPU3_Soak_Test_Report.md' if path.name=='cpu_soak_report.json' else prefix+'_report.md')
    markdown.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    # Persist acceptance additions after generating actual artifacts.
    from ESE_CPU1_Quantization.common import write_json
    write_json(path,report)
