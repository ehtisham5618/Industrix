"""Validate local dependency, seal evaluation splits, package and upload to Modal."""
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from workflow import digest, write_json

ROOT = Path(__file__).resolve().parent.parent
TASK = ROOT / "CME_OPT2_Model_Fine_Tuning"
DATASET = ROOT / "Hazard_Expansion/content_runtime/combined_dataset_augmented_v3"
ORIGINAL = ROOT / "Hazard_Expansion/content_runtime/combined_dataset"


def main():
    subprocess.run([sys.executable, str(ROOT / "Preprocessing/scripts/validate_yolo_dataset.py"),
                    "--dataset", str(DATASET), "--report", str(TASK / "reports/dataset_validation.json")], check=True)
    work = TASK / "runtime"
    work.mkdir(exist_ok=True)
    evaluation = {}
    for kind in ("images", "labels"):
        for split in ("val", "test"):
            files = list((DATASET / kind / split).iterdir())
            assert {p.name for p in files} == {p.name for p in (ORIGINAL / kind / split).iterdir()}
            for path in files:
                if not path.is_file():
                    continue
                rel = path.relative_to(DATASET).as_posix()
                evaluation[rel] = digest(path)
                assert digest(ORIGINAL / rel) == evaluation[rel]
    shutil.copy2(ROOT / "Backend/best.pt", work / "baseline.pt")
    shutil.copy2(ROOT / "Hazard_Expansion/content_runtime/expanded_model_results/expanded_12class_results.json", work / "historical_baseline.json")
    with zipfile.ZipFile(work / "dataset.zip", "w", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for path in sorted(DATASET.rglob("*")):
            if path.is_file() and path.suffix != ".cache":
                archive.write(path, path.relative_to(DATASET).as_posix())
    manifest = {"evaluation_files": evaluation, "baseline_sha256": digest(work / "baseline.pt"),
                "archive_sha256": digest(work / "dataset.zip"), "dependency_commit": "2c3353b0a74c5e4537328880ff0617ff8f9214ee",
                "dataset_version": "combined-12class-v3-hardnegative", "dataset": str(DATASET)}
    write_json(work / "input_manifest.json", manifest)
    write_json(TASK / "reports/input_summary.json", {k: v for k, v in manifest.items() if k != "evaluation_files"} | {"sealed_evaluation_files": len(evaluation)})
    import modal
    volume = modal.Volume.from_name("industirx-cme-opt2", create_if_missing=True)
    with volume.batch_upload(force=True) as upload:
        for name in ("dataset.zip", "baseline.pt", "input_manifest.json", "historical_baseline.json"):
            upload.put_file(work / name, "/" + name)
    print("Validated dataset uploaded; evaluation bytes sealed; baseline backed up.")


if __name__ == "__main__":
    main()
