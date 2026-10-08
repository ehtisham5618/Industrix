"""Produce the measured CPU time series and raw ring occupancy graph."""
import csv
from .benchmark import REPORTS

def main():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(2,1,figsize=(10,7),layout='constrained')
    for phase,color in [('baseline','#666666'),('optimized','#1764b5')]:
        with (REPORTS/f'{phase}_cpu_timeseries.csv').open() as f: rows=list(csv.DictReader(f))
        axes[0].plot([float(r['elapsed_seconds']) for r in rows],
            [float(r['cpu_percent']) for r in rows],color=color,label=f'{phase} system CPU')
        axes[0].plot([float(r['elapsed_seconds']) for r in rows],
            [float(r['normalized_process_cpu_percent']) for r in rows],
            color=color,alpha=.6,linestyle='--',label=f'{phase} normalized process CPU')
    axes[0].axhline(40,color='#ba2929',linestyle=':',label='40% acceptance threshold')
    axes[0].set(xlabel='Seconds in capture window',ylabel='Machine CPU (%)',ylim=(0,105),
                title='Actual three-stream FP32 CPU measurement')
    axes[0].legend(fontsize=8,ncol=2);axes[0].grid(alpha=.2)
    with (REPORTS/'optimized_buffer_occupancy.csv').open() as f: rows=list(csv.DictReader(f))
    for camera in ('camera_01','camera_02','camera_03'):
        axes[1].plot([float(r['elapsed_seconds']) for r in rows],[int(r[camera]) for r in rows],
                     label=camera,alpha=.7)
    axes[1].axhline(15,color='#ba2929',linestyle=':',label='15 raw-frame capacity')
    axes[1].set(xlabel='Seconds in capture window',ylabel='Raw frame references',ylim=(0,16),
                title='Bounded raw rings (occupancy alone does not prove zero overrun)')
    axes[1].legend(fontsize=8,ncol=4);axes[1].grid(alpha=.2)
    fig.savefig(REPORTS/'cpu_and_buffer_timeseries.png',dpi=140)
    plt.close(fig)

if __name__=='__main__':main()
