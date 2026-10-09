"""One final held-out evaluation and real model-attribution visual evidence."""
from __future__ import annotations
import csv
import json
from pathlib import Path
import cv2
import numpy as np
import torch
from PIL import Image,ImageDraw,ImageFont
from QCI_1_Surface_Defect_Segmentation.offline import no_network
from QCI_1_Surface_Defect_Segmentation.validation import file_hash,decode_image,read_annotations
from .common import REPORTS,TASK,CLASSES,deterministic,load_config,write_json
from .contracts import TrainingConfig,ModelArtifact
from .data import ManifestDataset,image_label
from .infer import DefectClassifier
from .metrics import metrics


def image_panel(canvas: Image.Image,picture: Image.Image,x: int,y: int,width: int=210,height: int=225) -> None:
    """Aspect-preserving display; no resynthesis or augmentation of evidence."""
    picture=picture.convert('RGB');picture.thumbnail((width,height));canvas.paste(picture,(x,y))


def plots(matrix: list[list[int]], history: Path) -> None:
    """Render scientific metrics with all figures closed after disk export."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axis=plt.subplots(figsize=(5,4));axis.imshow(matrix,cmap='Blues')
    for i in (0,1):
        for j in (0,1):axis.text(j,i,str(matrix[i][j]),ha='center',va='center',fontsize=18)
    axis.set_xticks([0,1],['normal','defect']);axis.set_yticks([0,1],['normal','defect']);axis.set_xlabel('Predicted');axis.set_ylabel('Actual');axis.set_title('QCI-2 untouched held-out test counts')
    fig.tight_layout();fig.savefig(REPORTS/'confusion_matrix.png',dpi=160);plt.close(fig)
    with history.open(encoding='utf-8') as stream:rows=list(csv.DictReader(stream))
    fig,axes=plt.subplots(1,3,figsize=(13,3.6));epochs=[int(r['epoch']) for r in rows]
    for key in ('train_loss','val_loss'):axes[0].plot(epochs,[float(r[key]) for r in rows],label=key)
    axes[0].set_title('Actual weighted cross entropy');axes[0].legend()
    axes[1].plot(epochs,[float(r['val_macro_f1']) for r in rows],label='validation macro F1');axes[1].plot(epochs,[float(r['val_accuracy']) for r in rows],label='validation accuracy');axes[1].legend()
    axes[2].plot(epochs,[float(r['head_lr']) for r in rows],label='head');axes[2].plot(epochs,[float(r['backbone_lr']) for r in rows],label='last block');axes[2].set_title('Cosine learning rates');axes[2].legend()
    for axis in axes:axis.set_xlabel('Epoch');axis.grid(alpha=.2)
    fig.tight_layout();fig.savefig(REPORTS/'training_curves.png',dpi=160);plt.close(fig)


def main() -> int:
    """Never select models using the test set; show every held-out test sample."""
    if (REPORTS/'test_metrics.json').exists():raise ValueError('Final held-out evaluation already recorded; preserve it instead of retuning')
    config=load_config(TASK/'configs/qci2_classifier.yaml');deterministic(config.seed,config.threads)
    artifact=ModelArtifact.model_validate_json((REPORTS/'model_artifact.json').read_text(encoding='utf-8'))
    if file_hash(config.manifest)!=artifact.manifest_sha256 or file_hash(config.records)!=artifact.records_sha256:raise ValueError('QCI-1 lineage changed after training')
    dataset=ManifestDataset(config,'test');service=DefectClassifier(config.output_dir/'best.pt',artifact.sha256)
    matrix=np.zeros((2,2),dtype=np.int64);records=[];failures=[];heatmaps=REPORTS/'heatmaps'
    canvas=Image.new('RGB',(1140,100+len(dataset)*280+60),'white');draw=ImageDraw.Draw(canvas)
    try:font=ImageFont.truetype('DejaVuSans.ttf',15);small=ImageFont.truetype('DejaVuSans.ttf',12)
    except OSError:font=ImageFont.load_default(size=15);small=ImageFont.load_default(size=12)
    headings=['Original source','Ground truth mask','Prediction / confidence','Model Grad-CAM','Model overlay']
    draw.text((15,12),'QCI-2 / ALL UNTOUCHED TEST SAMPLES - GROUND TRUTH IS NOT ATTRIBUTION',fill='#17344d',font=font)
    for index,heading in enumerate(headings):draw.text((15+index*225,55),heading,fill='#17344d',font=small)
    with no_network() as network:
        for index,row in enumerate(dataset.rows):
            actual=image_label(row)
            # Validate current input bytes through the QCI-1 adapter before inference.
            dataset[index]
            result=service.predict(dict(image=str(dataset.root/row.image.path),output_dir=str(heatmaps)))
            if result.status!='SUCCESS':raise ValueError(result.error_message)
            predicted=result.predicted_class_id;matrix[actual,predicted]+=1
            record=dict(sample_id=row.sample_id,ground_truth=actual,ground_truth_name=CLASSES[actual],prediction=result.model_dump(mode='json'))
            records.append(record)
            if actual!=predicted:failures.append(record)
            top=90+index*280
            draw.text((15,top),row.sample_id,fill='#17344d',font=small)
            with Image.open(dataset.root/row.image.path) as original:
                image_panel(canvas,original,15,top+25)
            with Image.open(dataset.root/str(row.annotation_path)) as mask:
                binary=np.asarray(mask,dtype=np.uint8)
                image_panel(canvas,Image.fromarray(binary*255),240,top+25)
            draw.multiline_text((465,top+45),f'Actual: {CLASSES[actual]}\nPredicted: {CLASSES[predicted]}\nConfidence: {result.confidence:.4f}\n{"CORRECT" if actual==predicted else "MISCLASSIFIED"}\nTarget: {result.heatmap.target_class_name}\n{"DEGENERATE CAM" if result.heatmap.degenerate else "Finite nonconstant CAM"}',fill='#17344d' if actual==predicted else '#a02b2b',font=small,spacing=7)
            with Image.open(result.heatmap.raw_heatmap_path) as picture:
                raw=np.asarray(picture,dtype=np.float32)/255
                color=cv2.cvtColor(cv2.applyColorMap(np.rint(raw*255).astype(np.uint8),cv2.COLORMAP_TURBO),cv2.COLOR_BGR2RGB)
                image_panel(canvas,Image.fromarray(color),690,top+25)
            with Image.open(result.heatmap.overlay_path) as picture:image_panel(canvas,picture,915,top+25)
            if raw.shape!=binary.shape or not np.isfinite(raw).all():raise ValueError('Real heatmap dimensions/finiteness failed')
            record['heatmap_validation']=dict(width=raw.shape[1],height=raw.shape[0],finite=True,minimum=float(raw.min()),maximum=float(raw.max()),target_class=result.heatmap.target_class_id)
            # Optional localization probe, not an interpretability/causality guarantee.
            if actual==1:
                record['localization_probe']=dict(pointing_game_hit=bool(binary.flat[int(np.argmax(raw))]>0),
                    energy_inside_mask=float(raw[binary>0].sum()/raw.sum()) if raw.sum()>0 else None,
                    method='Predicted-class explanation; quantized PNG energy. Sparse defect masks and coarse CAM limit conclusions.')
    canvas.save(REPORTS/'classifier_heatmap_sanity_grid.png')
    result=metrics(matrix)
    write_json(REPORTS/'test_predictions.json',records);write_json(REPORTS/'misclassifications.json',failures)
    write_json(REPORTS/'test_metrics.json',dict(**result.model_dump(),selected_model_sha256=artifact.sha256,test_evaluations=1,
        classification_target='Binary image-level mask presence:0 normal,1 defect',class_mapping=CLASSES,
        numeric_accuracy_target=None,numeric_latency_sla=None,offline_verified=True,external_connection_attempts=network.attempts,runtime_downloads=0,
        heatmaps_generated=len(records),finite_image_aligned_maps=len(records),degenerate_heatmaps=sum(r['prediction']['heatmap']['degenerate'] for r in records),
        all_test_samples_visualized=True,model_selection_used_test=False))
    plots(result.confusion_matrix,REPORTS/'training_history.csv')
    print(result.model_dump_json(indent=2));print('Saved every test prediction, genuine Grad-CAM, mask references and failure evidence.')
    return 0


if __name__=='__main__':raise SystemExit(main())
