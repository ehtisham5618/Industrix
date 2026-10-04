"""Download measured reports and selected weights from the task's Modal volume."""
from pathlib import Path
import modal

TASK = Path(__file__).resolve().parent


def main():
    volume = modal.Volume.from_name("industirx-cme-opt2")
    for remote, local in [("/reports", TASK / "reports"),
                          ("/runs", TASK / "runtime/runs")]:
        for entry in volume.listdir(remote, recursive=True):
            if entry.type.name != "FILE":
                continue
            path = Path(entry.path)
            target = local / path.relative_to(remote.lstrip("/")) if not path.is_absolute() else local / path.relative_to(remote)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("wb") as stream:
                for chunk in volume.read_file(entry.path):
                    stream.write(chunk)
    with (TASK / "runtime/training_contract.json").open("wb") as stream:
        for chunk in volume.read_file("/training_contract.json"):
            stream.write(chunk)
    print("Actual Modal artifacts downloaded.")


if __name__ == "__main__":
    main()
