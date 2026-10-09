"""The existing registry validates classification without fabricating detection mAP."""
import csv
from pathlib import Path
from tempfile import TemporaryDirectory
from Experiment_Tracking.scripts.validate_registry import validate
from QCI_2_Defect_Classifier.common import TASK


def test_classifier_registry_accepts_binary_metrics_and_rejects_missing_model() -> None:
    (TASK/'runtime').mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(dir=TASK/'runtime') as directory:
        root=Path(directory);tracking=root/'Experiment_Tracking';tracking.mkdir()
        (root/'fixture.pt').write_bytes(b'UNIT-FIXTURE-REFERENCE-ONLY');(root/'train.py').write_text('#fixture\n')
        (tracking/'model_registry.csv').write_text('model_version\nunit-classifier\n')
        (tracking/'alert_policy_registry.csv').write_text('policy_version,detector_model_version,threshold_config\n')
        fields=['run_id','sprint','task','experiment_type','model_version','best_weight_uri','dataset_version','git_commit','source_script','status']
        row=dict(run_id='unit-run',sprint='Sprint 2',task='QCI-2',experiment_type='classifier_training',model_version='unit-classifier',best_weight_uri='fixture.pt',dataset_version='unit-dataset',git_commit='unit-source',source_script='train.py',status='unit-test')
        def save() -> None:
            with (tracking/'experiments.csv').open('w',newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerow(row)
        save();assert validate(root)==0
        row['model_version']='missing-model';save();assert validate(root)==1
