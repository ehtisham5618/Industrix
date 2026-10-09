"""Append real classifier lineage to existing CSV and local MLflow tracking."""
from __future__ import annotations
import csv
import json
import subprocess
from pathlib import Path
from typing import Any
from Backend.offline_policy import configure_local_runtime
from .common import ROOT,REPORTS,TASK
from . import MODEL_VERSION


def append_row(path: Path,values: dict[str,Any],key: str) -> None:
    """Append one row without rewriting prior run history; reject duplicate IDs."""
    with path.open(encoding='utf-8',newline='') as stream:
        reader=csv.DictReader(stream);fields=reader.fieldnames
        if fields is None:raise ValueError('Registry header missing')
        if any(row[key]==str(values[key]) for row in reader):raise ValueError('Registry identity already recorded')
    row={field:str(values.get(field,'')) for field in fields}
    with path.open('a',encoding='utf-8',newline='') as stream:csv.DictWriter(stream,fieldnames=fields).writerow(row)


def main() -> None:
    """Log the actual selected model, train config, test metrics and attribution."""
    configure_local_runtime()
    for path,key,value in ((ROOT/'Experiment_Tracking/model_registry.csv','model_version',MODEL_VERSION),(ROOT/'Experiment_Tracking/experiments.csv','task','QCI-2')):
        with path.open(encoding='utf-8',newline='') as stream:
            if any(r[key]==value for r in csv.DictReader(stream)):raise ValueError('QCI-2 is already recorded; duplicate registry history preserved')
    # Existing guard allows Windows loopback IPC, blocks external TCP.
    from IFE_UI3_Demo_Packaging.offline_server import install_guard
    install_guard()
    from Experiment_Tracking.scripts.mlflow_utils import configure_tracking
    training=json.loads((REPORTS/'training_summary.json').read_text(encoding='utf-8'))
    evaluation=json.loads((REPORTS/'test_metrics.json').read_text(encoding='utf-8'))
    profile=json.loads((REPORTS/'inference_profile.json').read_text(encoding='utf-8'))
    config=training['training_config'];artifact=training['artifact']
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    mlflow=configure_tracking(ROOT/'Experiment_Tracking/mlruns')
    with mlflow.start_run(run_name='QCI-2 real binary classifier and Grad-CAM') as run:
        mlflow.set_tags(dict(task='QCI-2',sprint='Sprint 2',experiment_type='classifier_training',status='research_review_complete_release_pending',overall_dod='FAIL'))
        mlflow.log_params(dict(model_version=MODEL_VERSION,dataset_version=training['dataset_version'],manifest_sha256=artifact['manifest_sha256'],records_sha256=artifact['records_sha256'],
            architecture='resnet18',starting_weights_sha256=artifact['starting_weights_sha256'],checkpoint_sha256=artifact['sha256'],source_commit=commit,training_base_commit=artifact['source_commit'],
            input_shape=f"{config['height']}x{config['width']}",epochs_requested=config['epochs'],epochs_completed=training['epochs_completed'],best_epoch=training['best_epoch'],
            batch_size=config['batch_size'],optimizer=config['optimizer'],learning_rate=config['learning_rate'],head_learning_rate=config['head_learning_rate'],scheduler=config['scheduler'],seed=config['seed'],
            class_weights=json.dumps(training['class_weights']),heatmap_method='Grad-CAM',target_layer='layer4.1.conv2',device='cpu',commercial_permission='not obtained; noncommercial dataset'))
        mlflow.log_metrics(dict(accuracy=evaluation['accuracy'],macro_precision=evaluation['macro_precision'],macro_recall=evaluation['macro_recall'],macro_f1=evaluation['macro_f1'],
            best_validation_macro_f1=training['best_validation']['macro_f1'],rss_drift_percent=profile['drift_percent'],classifier_mean_ms=profile['classifier_latency']['mean_ms'],
            heatmap_mean_ms=profile['heatmap_latency']['mean_ms'],combined_mean_ms=profile['combined_latency']['mean_ms']))
        for name in ('training_summary.json','test_metrics.json','inference_profile.json','model_artifact.json','classifier_heatmap_sanity_grid.png','confusion_matrix.png'):
            mlflow.log_artifact(str(REPORTS/name))
        run_id=run.info.run_id
    notes=json.dumps(dict(checkpoint_sha256=artifact['sha256'],accuracy=evaluation['accuracy'],macro_f1=evaluation['macro_f1'],metrics='reports/qci2/test_metrics.json',
        report='reports/qci2/QCI_2_Production_Review.md',scope='Binary KolektorSDD mask-presence classifier, not7-class textile segmentation',license='CC BY-NC-SA4.0',commercial_permission=False),separators=(',',':'))
    append_row(ROOT/'Experiment_Tracking/model_registry.csv',dict(model_version=MODEL_VERSION,sprint='Sprint 2',task='QCI-2',stage='Binary surface-defect transfer learning',model_architecture='ResNet18',num_classes=2,
        purpose='Local noncommercial normal/defect classifier with model attribution',dataset='KolektorSDD curated QCI-1',dataset_version=training['dataset_version'],precision=evaluation['macro_precision'],recall=evaluation['macro_recall'],
        best_weight_uri=artifact['checkpoint'],last_weight_uri=str(Path(artifact['checkpoint']).with_name('last.pt')).replace('\\','/'),weight_reference_status='local selected checkpoint SHA256 verified',status='research_review_complete_release_pending',notes=notes), 'model_version')
    append_row(ROOT/'Experiment_Tracking/experiments.csv',dict(run_id=run_id,run_name='QCI-2 real binary classifier and Grad-CAM',sprint='Sprint 2',task='QCI-2',stage='Classifier training and held-out attribution evaluation',
        experiment_type='classifier_training',model_version=MODEL_VERSION,model_architecture='ResNet18',dataset='KolektorSDD curated QCI-1',dataset_version=training['dataset_version'],num_classes=2,
        epochs=training['epochs_completed'],batch_size=config['batch_size'],imgsz=f"{config['height']}x{config['width']}",optimizer=config['optimizer'],learning_rate=config['learning_rate'],weight_decay=config['weight_decay'],
        patience=config['patience'],seed=config['seed'],device='cpu',environment='Windows / Python3.12.9 / local PyTorch2.10.0 CPU',precision=evaluation['macro_precision'],recall=evaluation['macro_recall'],
        best_weight_uri=artifact['checkpoint'],last_weight_uri=str(Path(artifact['checkpoint']).with_name('last.pt')).replace('\\','/'),source_script='QCI_2_Defect_Classifier/train.py',git_commit=commit,
        status='research_review_complete_release_pending',tracking_origin='measured_local_run',notes=notes), 'run_id')
    write=dict(run_id=run_id,source_commit=commit,training_base_commit=artifact['source_commit'],model_version=MODEL_VERSION,tracking_uri=mlflow.get_tracking_uri(),
        checkpoint_sha256=artifact['sha256'],overall_dod='FAIL',reason='PR/access and commercial permission pending; existing repository quantitative failures remain')
    (REPORTS/'experiment_tracking.json').write_text(json.dumps(write,indent=2)+'\n',encoding='utf-8')
    print('Recorded actual existing-registry/local-MLflow QCI-2 run:',run_id)


if __name__=='__main__':main()
