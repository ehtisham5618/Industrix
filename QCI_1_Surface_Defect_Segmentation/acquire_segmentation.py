"""Explicit, one-time publisher download and faithful binary-mask import.

This setup command is separate from the strictly offline ingestion CLI. Original
Kolektor images and fine BMP masks remain in the checksummed publisher ZIP.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import numpy as np
from PIL import Image
import yaml

from .config import ROOT
from .validation import file_hash

URL = 'https://data.vicos.si/datasets/KSDD/KolektorSDD.zip'
SOURCE = 'https://www.vicos.si/resources/kolektorsdd/'
TASK = ROOT/'QCI_1_Surface_Defect_Segmentation'


def item_split(item: str, seed: int = 42) -> str:
    """Keep all photographed parts of one physical item in the same split."""
    score = int(hashlib.sha256(f'{seed}:{item}'.encode()).hexdigest()[:16], 16)/2**64
    return 'train' if score < .8 else 'val' if score < .9 else 'test'


def binary_mask(source: Image.Image) -> np.ndarray:
    """Normalize the publisher's binary 0/255 labels without changing geometry."""
    if source.mode not in ('1', 'L', 'P'):
        raise ValueError(f'Unsupported publisher mask mode: {source.mode}')
    if source.mode == 'P':
        rgb = np.asarray(source.convert('RGB'))
        if not (np.array_equal(rgb[:,:,0], rgb[:,:,1]) and np.array_equal(rgb[:,:,0], rgb[:,:,2])):
            raise ValueError('Publisher palette labels must render as grayscale binary values')
        values = rgb[:,:,0]
    else: values = np.asarray(source.convert('L'))
    if not set(np.unique(values)).issubset({0, 255}):
        raise ValueError('Publisher mask must contain only background 0 and defect 255')
    return (values == 255).astype(np.uint8)


def import_archive(archive: Path, destination: Path, evidence: Path) -> dict[str, object]:
    """Pair actual ZIP members, retain item groups and emit a provenance ledger."""
    if destination.exists():
        raise ValueError('Use a fresh destination; existing dataset bytes are preserved')
    destination.mkdir(parents=True)
    count = positives = 0
    splits = dict.fromkeys(('train', 'val', 'test'), 0)
    groups: dict[str, str] = {}; quarantined: list[dict[str, str]] = []
    with zipfile.ZipFile(archive) as zipped, (destination/'provenance.csv').open('w', encoding='utf-8', newline='') as ledger:
        members = zipped.namelist()
        if len(members) > 2000 or any(PurePosixPath(n).is_absolute() or '..' in PurePosixPath(n).parts or '\\' in n for n in members):
            raise ValueError('Unsafe or unexpectedly large publisher ZIP inventory')
        images = sorted(n for n in members if n.lower().endswith('.jpg'))
        masks = {n for n in members if n.lower().endswith('_label.bmp')}
        paired = {str(PurePosixPath(n).with_suffix(''))+'_label.bmp' for n in images}
        if paired != masks:
            raise ValueError('Publisher image/mask pairing is incomplete or contains orphans')
        writer = csv.writer(ledger)
        writer.writerow(['original_image', 'original_mask', 'split', 'item_group', 'image_sha256', 'original_mask_sha256', 'indexed_mask_sha256', 'foreground_pixels', 'status'])
        for name in images:
            relative = PurePosixPath(name)
            item = relative.parent.as_posix()
            split = item_split(item)
            groups[item] = split
            mask_name = str(relative.with_suffix(''))+'_label.bmp'
            if zipped.getinfo(name).file_size > 16_000_000 or zipped.getinfo(mask_name).file_size > 16_000_000:
                raise ValueError('Source member exceeds bounded import size')
            image_path = destination/'images'/split/Path(name)
            mask_path = destination/'masks'/split/Path(str(relative.with_suffix('.png')))
            image_path.parent.mkdir(parents=True, exist_ok=True)
            mask_path.parent.mkdir(parents=True, exist_ok=True)
            with zipped.open(name) as source, image_path.open('wb') as target:
                shutil.copyfileobj(source, target, length=1024*1024)
            with zipped.open(mask_name) as original:
                original_hash = hashlib.file_digest(original, 'sha256').hexdigest()
            try:
                with Image.open(image_path) as image, zipped.open(mask_name) as raw_mask:
                    with Image.open(raw_mask) as mask:
                        if image.size != mask.size or image.width*image.height > 2_000_000:
                            raise ValueError('Publisher dimensions incompatible or oversized')
                        normalized = binary_mask(mask)
            except ValueError as exc:
                rejected_image = destination/'quarantine'/Path(name)
                rejected_mask = destination/'quarantine'/Path(mask_name)
                rejected_image.parent.mkdir(parents=True, exist_ok=True)
                image_path.replace(rejected_image)
                with zipped.open(mask_name) as original, rejected_mask.open('wb') as target: shutil.copyfileobj(original, target)
                quarantined.append(dict(image=name, mask=mask_name, reason=str(exc)))
                writer.writerow([name, mask_name, split, item, file_hash(rejected_image), original_hash, '', '', 'QUARANTINED: '+str(exc)])
                continue
            Image.fromarray(normalized).save(mask_path)
            pixels = int(np.count_nonzero(normalized))
            writer.writerow([name, mask_name, split, item, file_hash(image_path), original_hash, file_hash(mask_path), pixels, 'VALID'])
            count += 1; positives += int(pixels > 0); splits[split] += 1
    metadata = dict(nc=1, names=['defect'], train='images/train', val='images/val', test='images/test',
                    source=SOURCE, license='CC BY-NC-SA 4.0',
                    mask_convention='Original BMP: 0 background, 255 defect; derived PNG: 0 background, 1 defect',
                    split_policy='No train/val/test supplied in this archive; seed42 hash of physical item ID, 80/10/10; every part of an item stays together')
    (destination/'data.yaml').write_text(yaml.safe_dump(metadata, sort_keys=False), encoding='utf-8')
    result: dict[str, object] = dict(source_page=SOURCE, download_url=URL, archive_sha256=file_hash(archive), archive_bytes=archive.stat().st_size,
        acquired_at=datetime.now(timezone.utc).isoformat(), dataset='KolektorSDD fine annotations (JIM2019)',
        license='CC BY-NC-SA 4.0', commercial_permission_obtained=False,
        usage='Local noncommercial research/review; not approved for commercial deployment',
        source_masks='Publisher fine pixel BMP annotations, not bounding-box approximations',
        canonical_classes=['defect'], unrelated_to_textile_seven_class_map=True,
        original_samples=len(images), quarantined_samples=quarantined,
        total_samples=count, positive_samples=positives, negative_samples=count-positives,
        split_counts=splits, physical_item_split_map=groups, item_group_cross_split_leakage=0,
        source_images_unchanged=True, mask_conversion='Exact 0/255 to 0/1 value mapping; geometry unchanged; no invented masks',
        ledger_sha256=file_hash(destination/'provenance.csv'), runtime_download_dependency=False)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    return result


def main() -> None:
    """Download only when explicitly requested; reuse the verified local archive."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download', action='store_true')
    parser.add_argument('--archive', type=Path, default=TASK/'runtime/downloads/KolektorSDD.zip')
    parser.add_argument('--destination', type=Path, default=TASK/'runtime/segmentation_dataset')
    args = parser.parse_args()
    if args.download:
        if args.archive.exists(): raise ValueError('Existing archive preserved; omit --download')
        args.archive.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(URL, timeout=60) as response, args.archive.open('wb') as target:
            total = 0
            while chunk := response.read(1024*1024):
                total += len(chunk)
                if total > 200_000_000: raise ValueError('Publisher download exceeds 200 MB budget')
                target.write(chunk)
    print(json.dumps(import_archive(args.archive, args.destination, ROOT/'reports/qci1/segmentation/source_acquisition.json'), indent=2))


if __name__ == '__main__': main()
