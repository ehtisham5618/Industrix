from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import math
import platform
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT/'ESE_CPU1_Quantization/reports'
RUNTIME = ROOT/'ESE_CPU1_Quantization/runtime'
SOURCE_VERSION = 'cme-opt2-focal-cosine-12class-v1'
DATA_VERSION = 'combined-12class-v3-hardnegative'
NAMES = ['baekra','color issues','contamination','cut','gray stitch','selvet','stain',
         'chemical hazard','fire','no helmet','smoke','water leak']


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def source_model(weights):
    from ultralytics import YOLO
    with (ROOT/'Experiment_Tracking/model_registry.csv').open(encoding='utf-8',newline='') as stream:
        row = next(row for row in csv.DictReader(stream) if row['model_version']==SOURCE_VERSION)
    assert digest(weights)==json.loads(row['notes'])['checkpoint_sha256'], 'Wrong source checkpoint'
    model = YOLO(str(weights))
    assert list(model.names.values())==NAMES and model.model.model[-1].nc==12
    architecture=model.model.yaml
    # The selected legacy YOLOv8 checkpoint predates the unified scales key.
    small = architecture.get('scale')=='s' or (
        architecture.get('depth_multiple')==0.33 and architecture.get('width_multiple')==0.5)
    assert small and architecture['backbone'][2][2]=='C2f', architecture
    return model


def dataset_config(path):
    import yaml
    config = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    names = list(config['names'].values()) if isinstance(config['names'],dict) else config['names']
    assert config['nc']==12 and names==NAMES
    directory = Path(config['path'])
    if not directory.is_absolute(): directory = ROOT/directory
    config['path'] = str(directory.resolve())
    for split in ('train','val','test'):
        assert (directory/config[split]).is_dir(), f'Missing existing {split} split'
    RUNTIME.mkdir(parents=True,exist_ok=True)
    target = RUNTIME/'evaluation.yaml'
    target.write_text(yaml.safe_dump(config),encoding='utf-8')
    return config, target


def environment():
    import psutil
    import subprocess
    packages = {}
    for name in ('ultralytics','torch','onnx','onnxruntime','openvino','nncf','numpy','mlflow'):
        try: packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: packages[name] = 'not installed'
    if platform.system()=='Windows':
        cpu = subprocess.check_output(['powershell','-NoProfile','-Command',
            '(Get-CimInstance Win32_Processor).Name'],text=True).strip()
    else:
        cpu = platform.processor()
    return dict(python=platform.python_version(),os=platform.platform(),cpu=cpu,
        is_intel='intel' in cpu.lower(),physical_cores=psutil.cpu_count(logical=False),
        logical_cores=psutil.cpu_count(),ram_bytes=psutil.virtual_memory().total,packages=packages,
        cpu_load_percent_at_snapshot=psutil.cpu_percent(interval=1),
        system_load_note='Shared user workstation; no exclusive machine isolation claimed.')


def accuracy_delta(before, after):
    if not all(math.isfinite(value) and 0<=value<=1 for value in (before,after)):
        raise ValueError('mAP must be finite on the0-1 scale')
    drop = (before-after)*100
    return dict(drop_pp=drop,relative_change_pct=(after-before)/before*100 if before else None,
                strict_0_8pp_pass=drop<0.8,dod_1_0pp_pass=drop<1.0)


def calibration(config, count=300, seed=42):
    """Coverage-aware seeded training selection, excluding byte-identical holdout images."""
    import random
    import numpy as np
    directory = Path(config['path'])
    training = sorted((directory/config['train']).glob('*'))
    training = [p for p in training if p.suffix.lower() in ('.jpg','.jpeg','.png')]
    holdout = {digest(p) for split in ('val','test') for p in (directory/config[split]).glob('*') if p.is_file()}
    rng = random.Random(seed); rng.shuffle(training)
    candidates, excluded = [], 0
    for image in training:
        sha = digest(image)
        if sha in holdout:
            excluded += 1; continue
        label = directory/'labels/train'/image.with_suffix('.txt').name
        classes = {int(line.split()[0]) for line in label.read_text().splitlines() if line.strip()}
        assert classes <= set(range(12))
        candidates.append((image,classes,sha))
    assert len(candidates)>=count
    selected, coverage = [], np.zeros(12,dtype=int)
    pool = list(candidates)
    # Balance image-level class coverage; seeded order breaks ties reproducibly.
    while len(selected)<count:
        index = max(range(len(pool)),key=lambda i:sum(1/(1+coverage[c]) for c in pool[i][1]))
        item = pool.pop(index); selected.append(item)
        for cls in item[1]: coverage[cls] += 1
    assert min(coverage)>0, 'Calibration must cover all12 classes'
    REPORTS.mkdir(parents=True,exist_ok=True)
    fields = ['image','label','sha256','classes','split']
    with (REPORTS/'calibration_manifest.csv').open('w',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields); writer.writeheader()
        for image,classes,sha in selected:
            writer.writerow(dict(image=image.relative_to(directory).as_posix(),
                label='labels/train/'+image.with_suffix('.txt').name,sha256=sha,
                classes=';'.join(map(str,sorted(classes))),split='train'))
    write_json(REPORTS/'calibration_summary.json',dict(count=len(selected),seed=seed,
        strategy='Seeded greedy inverse-current-image-class-coverage; training only',
        image_class_coverage=dict(zip(NAMES,map(int,coverage))),
        byte_identical_holdout_images_excluded=excluded,dataset_version=DATA_VERSION,
        manifest_sha256=digest(REPORTS/'calibration_manifest.csv')))
    manifest = RUNTIME/'calibration_images.txt'
    manifest.write_text('\n'.join(str(image.resolve()) for image,_,_ in selected)+'\n',encoding='utf-8')
    return [image for image,_,_ in selected], manifest


def preprocess(image):
    import numpy as np
    from ultralytics.data.augment import LetterBox
    img = LetterBox(new_shape=(640,640),auto=False,stride=32)(image=image)
    return np.ascontiguousarray(img[:,:,::-1].transpose(2,0,1)[None],dtype=np.float32)/255


def metrics(result):
    return dict(precision=float(result.box.mp),recall=float(result.box.mr),
        map50=float(result.box.map50),map50_95=float(result.box.map),
        per_class_ap50={NAMES[int(c)]:float(ap) for c,ap in zip(result.box.ap_class_index,result.box.ap50)})


def evaluate(artifact, data, mode, split='test'):
    from ultralytics import YOLO
    artifact=Path(artifact)
    selected=artifact
    if artifact.suffix=='.xml':
        # This pinned Ultralytics identifies OpenVINO by directory suffix, not XML.
        # Keep the mandated deployment path and validate byte-identical ignored aliases.
        import shutil
        selected=RUNTIME/'evaluation_openvino_model'
        selected.mkdir(parents=True,exist_ok=True)
        for path in (artifact,artifact.with_suffix('.bin'),artifact.parent/'metadata.yaml'):
            shutil.copy2(path,selected/path.name)
            assert digest(selected/path.name)==digest(path)
    result = YOLO(str(selected),task='detect').val(data=str(data),split=split,
        device='cpu',imgsz=640,batch=1,workers=0,rect=False,conf=0.001,iou=0.7,
        max_det=300,half=False,plots=False,save_json=False,verbose=False,
        project=str(RUNTIME/'validation'),name=mode,exist_ok=True)
    value = metrics(result)
    value.update(split=split,imgsz=640,batch=1,conf=0.001,iou=0.7,max_det=300,rect=False,
        artifact_sha256=digest(artifact),evaluation_yaml_sha256=digest(data))
    if artifact.suffix=='.xml':value['artifact_bin_sha256']=digest(artifact.with_suffix('.bin'))
    write_json(REPORTS/f'{mode}_metrics.json',value)
    return value
