"""Quarantine every exact duplicate copy using the completed local audit."""
from __future__ import annotations
import csv
import json
import shutil
from pathlib import Path
from .config import ROOT, inside
from .validation import file_hash


def main() -> None:
    """Preserve first-pass failures and original bytes; never pick a guessed copy."""
    output = ROOT/'reports/qci1/segmentation'
    dataset = ROOT/'QCI_1_Surface_Defect_Segmentation/runtime/segmentation_dataset'
    archive = output/'source_before_dedup'
    if archive.exists(): raise ValueError('Initial audit already preserved; no repeated curation')
    archive.mkdir()
    for path in output.iterdir():
        if path.is_file() and path.name != 'source_acquisition.json': shutil.copy2(path, archive/path.name)
    rejected = {}
    for line in (output/'leakage.jsonl').read_text(encoding='utf-8').splitlines():
        record = json.loads(line)
        source = inside(dataset/record['image_path'], dataset)
        if file_hash(source) != record['file_sha256']: raise ValueError('Source changed after audit')
        relative = Path(record['image_path'])
        original = Path(*relative.parts[2:]).as_posix()
        mask = dataset/'masks'/relative.parts[1]/Path(*relative.parts[2:]).with_suffix('.png')
        for path in (source, mask):
            target = dataset/'quarantine/duplicates'/path.relative_to(dataset)
            target.parent.mkdir(parents=True, exist_ok=True); path.replace(target)
        rejected[original] = dict(image=original, mask=str(Path(original).with_suffix(''))+'_label.bmp', reason='Exact decoded-content duplicate: all copies quarantined before export')
    ledger = dataset/'provenance.csv'
    with ledger.open(encoding='utf-8', newline='') as stream: rows = list(csv.DictReader(stream))
    count = positives = 0; splits = dict.fromkeys(('train','val','test'), 0)
    for row in rows:
        if row['original_image'] in rejected: row['status'] = 'QUARANTINED_DUPLICATE'
        if row['status'] == 'VALID':
            count += 1; positives += int(int(row['foreground_pixels'])>0); splits[row['split']] += 1
    with ledger.open('w',encoding='utf-8',newline='') as stream:
        writer = csv.DictWriter(stream,fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    evidence = output/'source_acquisition.json'
    result = json.loads(evidence.read_text(encoding='utf-8'))
    result['quarantined_samples'].extend(rejected.values())
    result.update(total_samples=count, positive_samples=positives, negative_samples=count-positives, split_counts=splits,
                  initial_audit='source_before_dedup/dataset_manifest.json', duplicate_copies_quarantined=len(rejected), ledger_sha256=file_hash(ledger))
    evidence.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print('Curated accepted pairs:',count,'positive:',positives,'negative:',count-positives,'splits:',splits)


if __name__ == '__main__': main()
