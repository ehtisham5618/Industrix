"""Corrupt QCI inputs cannot enter a global model SDK's auto-install fallback."""
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image
import pytest

from QCI_1_Surface_Defect_Segmentation.config import ROOT
from QCI_1_Surface_Defect_Segmentation.validation import decode_image
from QCI_1_Surface_Defect_Segmentation.errors import InvalidSampleError
from tests.test_qci1_ingestion import dataset

def test_foreign_ultralytics_opener_is_bypassed_without_import_or_install():
    base=ROOT/'QCI_1_Surface_Defect_Segmentation/runtime';base.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='decoder_',dir=base) as name:
        cfg=dataset(Path(name));bad=cfg.dataset_root/'images/train/bad.png';bad.write_bytes(b'corrupt')
        native=Image.open
        # Accommodate an already-loaded SDK during the complete repository suite.
        if native.__module__=='ultralytics.utils.patches':
            import sys
            native=sys.modules['ultralytics.utils.patches']._image_open
        calls=[]
        def foreign(*args,**kwargs):calls.append(args);raise AssertionError('Would attempt installation')
        foreign.__module__='ultralytics.utils.patches'
        with patch('PIL.Image.open',foreign),patch.dict('sys.modules',{'ultralytics.utils.patches':SimpleNamespace(_image_open=native)}):
            with pytest.raises(InvalidSampleError) as failure:decode_image(bad,cfg)
        assert failure.value.issue.code=='CORRUPTED_IMAGE' and calls==[]
