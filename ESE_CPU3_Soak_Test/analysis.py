"""Trend-based soak analysis; operational FPS never substitutes for engine capacity."""
from __future__ import annotations

import statistics
from SED_3_Stress_Testing.scripts.analysis import linear_slope,summarize_values


def values(rows,key):
    return [float(r[key]) for r in rows if r.get(key) not in (None,'','NA')]


def optional_stats(rows,key):
    series=values(rows,key)
    return summarize_values(series) if series else None


def memory_trend(rows,field,minimum_growth_mb=10):
    usable=[r for r in rows if not r.get('warmup') and r.get(field) not in (None,'','NA')]
    if len(usable)<4:
        return dict(leak_detected=None,evidence_sufficient=False,reason='Insufficient post-warmup samples')
    xs=[float(r['soak_elapsed_seconds'])/3600 for r in usable]
    ys=values(usable,field)
    # Fit overall and late-run trends; distinguish bounded cache fill from
    # continuing material growth. Thresholds are declared before measurement.
    slope=linear_slope(xs,ys)
    span=max(xs)-min(xs)
    early=[v for x,v in zip(xs,ys) if x<=min(xs)+min(1/6,span/4)]
    late=[v for x,v in zip(xs,ys) if x>=max(xs)-min(1/6,span/4)]
    tail=[(x,v) for x,v in zip(xs,ys) if x>=max(xs)-min(1/3,span/2)]
    late_slope=linear_slope([x for x,_ in tail],[v for _,v in tail])
    early_mean,late_mean=statistics.fmean(early),statistics.fmean(late)
    threshold=max(minimum_growth_mb,.05*early_mean)
    slope_threshold=max(minimum_growth_mb,.02*early_mean)
    growth=late_mean-early_mean
    suspected=slope>slope_threshold and growth>threshold and late_slope>slope_threshold
    return dict(leak_detected=suspected,evidence_sufficient=True,slope_mb_per_hour=slope,
        final_twenty_minute_slope_mb_per_hour=late_slope,early_window_mean_mb=early_mean,
        final_window_mean_mb=late_mean,window_growth_mb=growth,material_growth_threshold_mb=threshold,
        slope_threshold_mb_per_hour=slope_threshold,
        reason='Sustained material growth in overall and late trends' if suspected else
               'No sustained material upward trend supported by all indicators; bounded cache/history fill is allowed')


def soak_windows(rows):
    result=[]
    for index in range(6):
        data=[r for r in rows if not r.get('warmup') and index*600<=float(r['soak_elapsed_seconds'])<(index+1)*600]
        if not data:continue
        times=[float(r['sample_interval_seconds']) for r in data]
        frames=sum(int(r['evaluated_delta']) for r in data)
        result.append(dict(window=f'{index*10}-{(index+1)*10} min',samples=len(data),
            aggregate_fps=frames/max(.000001,sum(times)),
            system_cpu=optional_stats(data,'system_cpu_pct'),process_cpu=optional_stats(data,'normalized_process_cpu_pct'),
            rss=optional_stats(data,'process_rss_mb'),python_alloc=optional_stats(data,'tracemalloc_current_mb'),
            python_peak=optional_stats(data,'tracemalloc_peak_mb'),frequency=optional_stats(data,'cpu_freq_mhz'),
            temperature=optional_stats(data,'cpu_temp_c')))
    return result


def evaluate_dod(status,actual_duration,crashes,memory,operational_fps,capacity_fps,clean_shutdown):
    done=status=='completed' and actual_duration>=3600
    stable=all(m.get('evidence_sufficient') and m.get('leak_detected') is False for m in memory.values())
    # Repository/task defines the integrated operational pipeline as primary.
    # Capacity is separately evaluated to expose the sampling conflict.
    target=operational_fps>=45
    return dict(completed_60_minutes=done,no_crashes=crashes==0,
        no_memory_leak_evidence=done and stable,throughput_target_met=target,
        inference_capacity_target_met=capacity_fps is not None and capacity_fps>=45,
        clean_shutdown=clean_shutdown,
        overall_pass=done and crashes==0 and stable and target and clean_shutdown)


def thermal_analysis(rows):
    frequency=optional_stats(rows,'cpu_freq_mhz')
    temperature=optional_stats(rows,'cpu_temp_c')
    return dict(temperature_available=temperature is not None,frequency_available=frequency is not None,
        temperature=temperature,frequency=frequency,
        mean_temp_c=temperature['mean'] if temperature else None,
        peak_temp_c=temperature['max'] if temperature else None,
        mean_freq_mhz=frequency['mean'] if frequency else None,min_freq_mhz=frequency['min'] if frequency else None,
        throttling_detected=None,
        throttling_evidence='Unable to determine due to unavailable telemetry: no exposed CPU thermal-limit or OS throttling counter. Frequency variation alone is not evidence of thermal throttling.',
        frequency_source='psutil.cpu_freq; on Windows reported frequency may be nominal and is not a per-core real-time thermal counter')
