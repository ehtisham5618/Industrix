"""QCI-2 synthetic fixtures verify mechanics, never production model performance."""
from __future__ import annotations
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import numpy as np
import pytest
import torch
from torch import nn
from PIL import Image
from pydantic import ValidationError
from QCI_1_Surface_Defect_Segmentation.contracts import SegmentationSample,ImageRecord,SegmentationAnnotation
from QCI_1_Surface_Defect_Segmentation.offline import no_network
from QCI_2_Defect_Classifier.common import TASK,CLASSES,deterministic
from QCI_2_Defect_Classifier.contracts import TrainingConfig,PredictionResult,PredictionRequest
from QCI_2_Defect_Classifier.data import image_label
from QCI_2_Defect_Classifier.infer import DefectClassifier,grad_cam,normalize_cam
from QCI_2_Defect_Classifier.metrics import metrics
from QCI_2_Defect_Classifier.model import build_model,load_checkpoint,training_mode


@pytest.fixture(scope='module')
def fixture_files():
    """One explicitly untrained random ResNet checkpoint and a tiny local image."""
    deterministic(123,1)
    (TASK/'runtime').mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(dir=TASK/'runtime') as directory:
        root=Path(directory)
        cfg=TrainingConfig(manifest=root/'fixture_manifest.json',records=root/'fixture_records.jsonl',output_dir=root/'run',starting_weights=root/'unused.pt',starting_sha256='0'*64,height=64,width=64)
        model=build_model()
        state=dict(architecture='resnet18',model_version='UNIT-FIXTURE-NOT-PRODUCTION',classes=CLASSES,state_dict=model.state_dict(),config=cfg.model_dump(mode='json'))
        torch.save(state,root/'fixture.pt')
        image=np.random.default_rng(123).integers(0,256,(80,50,3),dtype=np.uint8)
        Image.fromarray(image).save(root/'image.png');(root/'corrupt.png').write_bytes(b'broken actual image')
        yield root


def test_real_resnet_forward_backward_and_checkpoint_reload(fixture_files: Path) -> None:
    model,state=load_checkpoint(fixture_files/'fixture.pt');training_mode(model)
    before=model.fc.weight.detach().clone();optim=torch.optim.AdamW(model.fc.parameters(),lr=.01)
    logits=model(torch.randn(2,3,64,64));assert logits.shape==(2,2)
    loss=nn.functional.cross_entropy(logits,torch.tensor([0,1]));assert torch.isfinite(loss)
    loss.backward();assert torch.isfinite(model.fc.weight.grad).all();optim.step()
    assert not torch.equal(before,model.fc.weight)
    assert all(not module.training for module in model.modules() if isinstance(module,nn.BatchNorm2d))
    state['state_dict']=model.state_dict();torch.save(state,fixture_files/'roundtrip.pt')
    restored,_=load_checkpoint(fixture_files/'roundtrip.pt');assert torch.equal(restored.fc.weight,model.fc.weight)


def test_valid_prediction_and_same_source_size_heatmap(fixture_files: Path) -> None:
    service=DefectClassifier(fixture_files/'fixture.pt')
    result=service.predict(dict(image=str(fixture_files/'image.png'),output_dir=str(fixture_files/'out')))
    # Outputs cannot write into the source folder. Explicit sibling output below.
    assert result.status=='FAILED'
    destination=TASK/'runtime'/(fixture_files.name+'_heatmaps')
    try:
        result=service.predict(dict(image=str(fixture_files/'image.png'),output_dir=str(destination)))
        assert result.status=='SUCCESS';assert result.predicted_class_id in (0,1)
        assert 0<=result.confidence<=1 and len(result.class_scores)==2
        assert sum(c.score for c in result.class_scores)==pytest.approx(1)
        assert result.heatmap.width==50 and result.heatmap.height==80
        assert Image.open(result.heatmap.raw_heatmap_path).size==(50,80)
        assert Image.open(result.heatmap.overlay_path).size==(50,80)
        assert not service.target_layer._forward_hooks
    finally:
        # Only exact files created by this test, no recursive deletion.
        if destination.exists():
            for p in destination.iterdir():p.unlink()
            destination.rmdir()


@pytest.mark.parametrize('name',['corrupt.png','missing.png'])
def test_corrupt_or_missing_image_returns_failure(fixture_files: Path,name: str) -> None:
    result=DefectClassifier(fixture_files/'fixture.pt').predict(dict(image=str(fixture_files/name)))
    assert result.status=='FAILED' and result.confidence is None and result.heatmap is None and result.model_version is None


@pytest.mark.parametrize('target',[2,-1,True,1.5,'1'])
def test_invalid_target_class_is_controlled(fixture_files: Path,target: object) -> None:
    result=DefectClassifier(fixture_files/'fixture.pt').predict(dict(image=str(fixture_files/'image.png'),target_class=target))
    assert result.status=='FAILED' and not result.class_scores


def test_missing_model_no_download(fixture_files: Path) -> None:
    with no_network() as audit:
        result=DefectClassifier(fixture_files/'missing.pt').predict(dict(image=str(fixture_files/'image.png')))
    assert result.status=='FAILED' and audit.attempts==0


def test_class_map_mismatch_rejected(fixture_files: Path) -> None:
    state=torch.load(fixture_files/'fixture.pt',weights_only=True);state['classes']={0:'stain',1:'cut'}
    torch.save(state,fixture_files/'bad_map.pt')
    result=DefectClassifier(fixture_files/'bad_map.pt').predict(dict(image=str(fixture_files/'image.png')))
    assert result.status=='FAILED' and 'mapping' in result.error_message


def test_invalid_model_bytes_and_checksum_rejected(fixture_files: Path) -> None:
    (fixture_files/'broken.pt').write_bytes(b'not a checkpoint')
    assert DefectClassifier(fixture_files/'broken.pt').predict(dict(image=str(fixture_files/'image.png'))).status=='FAILED'
    assert DefectClassifier(fixture_files/'fixture.pt','0'*64).predict(dict(image=str(fixture_files/'image.png'))).status=='FAILED'


def test_eval_determinism_scoped_hooks_and_offline(fixture_files: Path) -> None:
    prior_grad_mode=torch.is_grad_enabled()
    with no_network() as audit:
        service=DefectClassifier(fixture_files/'fixture.pt');baseline=None
        for _ in range(12):
            result=service.predict(dict(image=str(fixture_files/'image.png'),target_class=1))
            assert result.status=='SUCCESS' and result.heatmap.target_class_id==1
            values=[s.score for s in result.class_scores]
            if baseline is None:baseline=values
            assert values==pytest.approx(baseline,abs=1e-7)
            assert len(service.target_layer._forward_hooks)==0
            assert all(p.grad is None for p in service.model.parameters())
    assert audit.attempts==0 and torch.is_grad_enabled()==prior_grad_mode


class ToyAttribution(nn.Module):
    """Explicit synthetic CNN has distinct red and green class activations."""
    def __init__(self) -> None:
        super().__init__();self.conv=nn.Conv2d(3,2,1,bias=False)
        with torch.no_grad():self.conv.weight.zero_();self.conv.weight[0,0]=1;self.conv.weight[1,1]=1

    def forward(self,value: torch.Tensor) -> torch.Tensor:
        return self.conv(value).mean((2,3))


def test_grad_cam_is_model_and_class_specific_not_a_mask() -> None:
    model=ToyAttribution();value=torch.zeros(1,3,8,8);value[0,0,:,:4]=1;value[0,1,:,4:]=1
    first,_=grad_cam(model,value,0,model.conv);second,_=grad_cam(model,value,1,model.conv)
    assert first[:,:4].mean()>first[:,4:].mean();assert second[:,4:].mean()>second[:,:4].mean()
    assert first.min()==0 and first.max()==1 and not np.array_equal(first,second)
    assert len(model.conv._forward_hooks)==0


@pytest.mark.parametrize('bad',[float('nan'),float('inf')])
def test_nonfinite_cam_rejected(bad: float) -> None:
    with pytest.raises(ValueError):normalize_cam(np.array([[bad,0]],dtype=np.float32))


def test_degenerate_cam_and_failure_contract() -> None:
    cam,degenerate=normalize_cam(np.ones((3,4),dtype=np.float32));assert degenerate and not cam.any()
    with pytest.raises(ValidationError):PredictionResult(status='FAILED',sample_id='fixture',confidence=.9)
    with pytest.raises(ValidationError):PredictionResult(status='SUCCESS',sample_id='fixture')


def sample(positive: bool) -> SegmentationSample:
    """Typed tiny QCI-1 record fixture for deterministic label derivation."""
    return SegmentationSample(sample_id='train/fixture',split='train',image=ImageRecord(path='fixture.png',width=8,height=8),annotation_path='fixture_mask.png',
        annotation_kind='indexed_mask',source_valid=True,segmentation_valid=True,empty_annotation=not positive,
        annotations=[SegmentationAnnotation(class_id=0,kind='indexed_mask',foreground_pixels=2)] if positive else [])


def test_qci1_normal_and_defect_derivation() -> None:
    assert image_label(sample(False))==0 and image_label(sample(True))==1
    invalid=sample(True);invalid.annotations[0].class_id=1
    with pytest.raises(ValueError):image_label(invalid)
    invalid=sample(True);invalid.empty_annotation=True
    with pytest.raises(ValueError):image_label(invalid)


def test_known_confusion_macro_metrics() -> None:
    result=metrics(np.array([[8,2],[1,3]],dtype=np.int64))
    assert result.samples==14 and result.accuracy==pytest.approx(11/14)
    assert result.per_class[1].precision==pytest.approx(3/5) and result.per_class[1].recall==pytest.approx(3/4)
    with pytest.raises(ValueError):metrics(np.zeros((2,2),dtype=np.int64))


@pytest.mark.parametrize('changes',[dict(epochs=0),dict(batch_size=100),dict(workers=8),dict(height=1024,width=1024),dict(manifest='https://example.com/m.json'),dict(learning_rate=float('nan')),dict(starting_sha256='bad')])
def test_malformed_config(changes: dict[str,object],fixture_files: Path) -> None:
    config=dict(manifest=str(fixture_files/'m.json'),records=str(fixture_files/'r.jsonl'),output_dir=str(fixture_files/'run'),starting_weights=str(fixture_files/'start.pt'),starting_sha256='0'*64)
    config.update(changes)
    with pytest.raises(ValidationError):TrainingConfig.model_validate(config)
