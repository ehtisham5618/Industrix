"""Scientific plots from measured deployment sizes, latency and class AP."""
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from .common import ROOT,REPORTS,NAMES


def main():
    report=json.loads((ROOT/'SED_3_Stress_Testing/reports/quant_report.json').read_text())
    source=json.loads((REPORTS/'source_lineage.json').read_text())
    artifacts=report['artifacts']
    names=['PyTorch checkpoint','ONNX FP16','OpenVINO INT8']
    colors=['#596ba4','#258d89','#c76b39']
    figure,axes=plt.subplots(1,2,figsize=(11,4.5),constrained_layout=True)
    values=[source['source_bytes']/1e6,artifacts['artifacts']['onnx_fp16']['bytes']/1e6,
        artifacts['combined_core_decimal_mb']]
    bars=axes[0].bar(names,values,color=colors)
    axes[0].bar_label(bars,fmt='%.2f',padding=3)
    axes[0].axhline(6.5,color='#ac2636',linestyle='--',label='INT8 target: <6.5 MB')
    axes[0].set(title='Actual artifact size (IR = XML + BIN)',ylabel='Decimal MB',ylim=(0,max(values)*1.2))
    axes[0].legend(fontsize=8)
    values=[report['latency'][name]['mean_ms'] for name in ('fp32_cpu','onnx_fp16_cpu','openvino_int8_cpu')]
    bars=axes[1].bar(['PyTorch FP32','ORT FP16 artifact','OpenVINO INT8'],values,color=colors)
    axes[1].bar_label(bars,fmt='%.2f',padding=3)
    axes[1].axhline(20,color='#ac2636',linestyle='--',label='INT8 target: <20 ms')
    axes[1].set(title='Mean CPU model-only latency (200 calls)',ylabel='Milliseconds',ylim=(0,max(values)*1.2))
    axes[1].legend(fontsize=8)
    figure.suptitle(f"ESE-CPU1: {report['status']} — batch 1, 640×640, measured on Intel i5-7200U")
    figure.savefig(REPORTS/'cpu_deployment_comparison.png',dpi=160);plt.close(figure)
    before=report['accuracy']['fp32']['per_class_ap50']
    after=report['accuracy']['int8']['per_class_ap50']
    values=[(after[name]-before[name])*100 for name in NAMES]
    figure,axis=plt.subplots(figsize=(10,4.5),constrained_layout=True)
    bars=axis.bar(NAMES,values,color=['#278f83' if value>=0 else '#b94348' for value in values])
    axis.bar_label(bars,fmt='%.2f',padding=3,fontsize=8)
    axis.axhline(0,color='#404040',linewidth=0.8)
    axis.set(title='OpenVINO INT8 minus FP32: same held-out test split',ylabel='AP@50 change (percentage points)')
    axis.tick_params(axis='x',rotation=45)
    for label in axis.get_xticklabels():label.set_horizontalalignment('right')
    axis.margins(y=0.2)
    figure.savefig(REPORTS/'per_class_quantization_delta.png',dpi=160);plt.close(figure)
    print('Actual deployment comparison and per-class AP graphs generated.')


if __name__=='__main__':main()
