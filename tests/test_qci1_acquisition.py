"""Explicit publisher-import fixtures: no network and no false textile labels."""
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import zipfile

import numpy as np
from PIL import Image
import pytest

from QCI_1_Surface_Defect_Segmentation.acquire_segmentation import binary_mask, import_archive, item_split
from QCI_1_Surface_Defect_Segmentation.config import ROOT


def encoded(image: Image.Image, format_: str) -> bytes:
    buffer = BytesIO(); image.save(buffer, format=format_); return buffer.getvalue()


def test_exact_binary_mask_geometry() -> None:
    raw = np.array([[0, 255], [255, 0]], dtype=np.uint8)
    assert np.array_equal(binary_mask(Image.fromarray(raw)), raw//255)


@pytest.mark.parametrize('value', [1, 128, 254])
def test_import_rejects_undeclared_mask_values(value: int) -> None:
    with pytest.raises(ValueError): binary_mask(Image.fromarray(np.array([[value]], dtype=np.uint8)))


def test_physical_item_group_stays_in_one_split() -> None:
    assert item_split('kos01') == item_split('kos01')
    assert {item_split(f'kos{x:02}') for x in range(1, 100)} == {'train', 'val', 'test'}


def test_binary_palette_is_interpreted_through_its_actual_colors() -> None:
    source = Image.fromarray(np.array([[0, 10]], dtype=np.uint8)).convert('P')
    palette = [0]*768; palette[30:33] = [255,255,255]; source.putpalette(palette)
    assert binary_mask(source).tolist() == [[0,1]]
    palette[30:33] = [255,0,0]; source.putpalette(palette)
    with pytest.raises(ValueError, match='grayscale'): binary_mask(source)


def test_zip_import_source_fidelity_and_missing_mask_rejection() -> None:
    with TemporaryDirectory(dir=ROOT/'QCI_1_Surface_Defect_Segmentation/runtime') as directory:
        root = Path(directory); archive = root/'source.zip'
        image = encoded(Image.new('RGB', (4, 4), 'red'), 'JPEG')
        mask = encoded(Image.new('L', (4, 4), 255), 'BMP')
        with zipfile.ZipFile(archive, 'w') as zipped:
            zipped.writestr('kos01/Part0.jpg', image); zipped.writestr('kos01/Part0_label.bmp', mask)
            zipped.writestr('kos01/Part1.jpg', image); zipped.writestr('kos01/Part1_label.bmp', mask)
        result = import_archive(archive, root/'dataset', root/'evidence.json')
        assert result['canonical_classes'] == ['defect']
        assert result['total_samples'] == result['positive_samples'] == 2
        split = item_split('kos01')
        assert (root/'dataset/images'/split/'kos01/Part0.jpg').read_bytes() == image
        assert set(np.unique(np.asarray(Image.open(root/'dataset/masks'/split/'kos01/Part0.png')))) == {1}
        with pytest.raises(ValueError, match='fresh destination'):
            import_archive(archive, root/'dataset', root/'evidence.json')
        with zipfile.ZipFile(root/'bad.zip', 'w') as zipped: zipped.writestr('kos01/Part0.jpg', image)
        with pytest.raises(ValueError, match='pairing'):
            import_archive(root/'bad.zip', root/'bad_dataset', root/'bad_evidence.json')


def test_ambiguous_publisher_pixels_are_quarantined_without_fabrication() -> None:
    with TemporaryDirectory(dir=ROOT/'QCI_1_Surface_Defect_Segmentation/runtime') as directory:
        root = Path(directory); archive = root/'source.zip'
        image = encoded(Image.new('RGB', (4, 4), 'red'), 'JPEG')
        mask = encoded(Image.new('L', (4, 4), 85), 'BMP')
        with zipfile.ZipFile(archive, 'w') as zipped:
            zipped.writestr('kos01/Part0.jpg', image); zipped.writestr('kos01/Part0_label.bmp', mask)
        result = import_archive(archive, root/'dataset', root/'evidence.json')
        assert result['original_samples'] == 1 and result['total_samples'] == 0
        assert len(result['quarantined_samples']) == 1
        assert (root/'dataset/quarantine/kos01/Part0_label.bmp').read_bytes() == mask
        assert not list((root/'dataset/masks').rglob('*.png'))
