"""Plot measured alert counts and event recall; never turn missing delays into zero."""
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

REPORTS = Path(__file__).resolve().parent/'reports'


def main():
    summary = json.loads((REPORTS/'benchmark_summary.json').read_text())
    alerts = {}
    for mode in ('baseline', 'bytetrack'):
        with (REPORTS/f'{mode}_alerts.csv').open(newline='', encoding='utf-8') as stream:
            alerts[mode] = list(csv.DictReader(stream))
    with (REPORTS/'per_event_latency.csv').open(newline='', encoding='utf-8') as stream:
        events = list(csv.DictReader(stream))
    classes = sorted({r['class_name'] for r in events + alerts['baseline'] + alerts['bytetrack']})
    fields = ['class_name', 'baseline_false_alerts', 'tracked_false_alerts', 'fp_reduction_pct',
              'true_events', 'baseline_events_triggered', 'tracked_events_triggered',
              'tracked_events_within_2s', 'tracked_missed_events']
    rows = []
    for name in classes:
        b = sum(r['false_alert']=='True' for r in alerts['baseline'] if r['class_name']==name)
        t = sum(r['false_alert']=='True' for r in alerts['bytetrack'] if r['class_name']==name)
        ground = [r for r in events if r['class_name']==name and r['mode']=='bytetrack']
        before = [r for r in events if r['class_name']==name and r['mode']=='baseline']
        rows.append(dict(zip(fields, [name, b, t, (b-t)/b*100 if b else 'unavailable',
            len(ground), sum(r['missed']=='False' for r in before),
            sum(r['missed']=='False' for r in ground), sum(r['within_2s']=='True' for r in ground),
            sum(r['missed']=='True' for r in ground)])))
    with (REPORTS/'class_comparison.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)
    figure, axes = plt.subplots(1, 2, figsize=(10, 4), constrained_layout=True)
    counts = [summary['baseline']['false_alerts'], summary['bytetrack']['false_alerts']]
    bars = axes[0].bar(['CME-2 baseline', 'ByteTRACK + 15'], counts, color=['#6366a2', '#269c91'])
    axes[0].bar_label(bars, padding=4)
    axes[0].set(title='Formal false alerts (600 seconds)', ylabel='Alert events', ylim=(0, max(counts+[1])*1.25))
    observed = [sum(r['mode']=='baseline' and r['missed']=='False' for r in events), summary['events_triggered']]
    bars = axes[1].bar(['CME-2 baseline', 'ByteTRACK + 15'], observed, color=['#6366a2', '#269c91'])
    axes[1].bar_label(bars, padding=4)
    axes[1].axhline(summary['true_events'], linestyle='--', color='#b62d31', label=f"All {summary['true_events']} annotated events")
    axes[1].set(title='True scene events receiving an alert', ylabel='Events', ylim=(0, summary['true_events']+3))
    axes[1].legend(loc='upper right', fontsize=8)
    figure.suptitle(f"CME-OPT3: {summary['status']} — {summary['missed_events']} of "
                   f"{summary['true_events']} true events missed", fontsize=12)
    figure.savefig(REPORTS/'factory_alert_comparison.png', dpi=160)
    plt.close(figure)
    print('Measured class comparison and alert/recall graph generated.')


if __name__ == '__main__': main()
