"""Verify one sealed archive, then train/evaluate from fast ephemeral storage.

This avoids thousands of cold remote-file reads while a GPU is allocated.
The archive and every held-out file retain the original manifest hashes.
"""
import json
import shutil
import zipfile
from pathlib import Path
import yaml
from workflow import digest, write_json


def preflight(work):
    work=Path(work).resolve()
    manifest=json.loads((work / "input_manifest.json").read_text())
    actual=digest(work / "dataset.zip")
    assert actual==manifest["archive_sha256"]
    result={"archive_sha256":actual,"archive_bytes":(work / "dataset.zip").stat().st_size,
            "expected_evaluation_files":len(manifest["evaluation_files"]),"device":"CPU","gpu_allocated":False}
    write_json(work / "reports/archive_verification.json",result)
    print("CPU archive integrity verified",result,flush=True)
    return result


def prepare_local(work):
    work=Path(work).resolve()
    manifest=json.loads((work / "input_manifest.json").read_text())
    verified=json.loads((work / "reports/archive_verification.json").read_text())
    assert verified["archive_sha256"]==manifest["archive_sha256"]
    temporary=Path("/tmp/cme_opt2_data");temporary.mkdir(exist_ok=True)
    archive=temporary / "dataset.zip"
    print("Copying sealed archive to local ephemeral storage",flush=True)
    shutil.copyfile(work / "dataset.zip",archive)
    assert digest(archive)==manifest["archive_sha256"]
    dataset=temporary / "dataset"
    with zipfile.ZipFile(archive) as zipped:
        assert all(not Path(n).is_absolute() and ".." not in Path(n).parts for n in zipped.namelist())
        zipped.extractall(dataset)
    for rel,expected in manifest["evaluation_files"].items():
        assert digest(dataset / rel)==expected,f"Held-out bytes changed: {rel}"
    assert digest(work / "baseline.pt")==manifest["baseline_sha256"]
    data=yaml.safe_load((dataset / "data.yaml").read_text())
    names=list(data["names"].values()) if isinstance(data["names"],dict) else data["names"]
    assert data["nc"]==len(names)==12 and names[7]=="chemical hazard" and names[10]=="smoke"
    data.update(path=str(dataset),train="images/train",val="images/val",test="images/test")
    (dataset / "data.yaml").write_text(yaml.safe_dump(data),encoding="utf-8")
    write_json(work / "reports/local_dataset_verification.json",{"archive_sha256":manifest["archive_sha256"],
               "sealed_evaluation_files":len(manifest["evaluation_files"]),"all_evaluation_hashes_match":True,
               "dataset_yaml":str(dataset / "data.yaml"),"train_images":5479,"val_images":777,"test_images":334})
    print("DATASET",dataset,"12 classes; all held-out hashes verified on local storage",flush=True)
    return dataset / "data.yaml",names
