"""Fetch measured output and the ignored MP4 derivative from the task volume."""
from pathlib import Path
import modal


def main():
    root = Path(__file__).resolve().parents[1]
    reports = root/'CME_OPT3_ByteTrack/reports'
    reports.mkdir(exist_ok=True)
    volume = modal.Volume.from_name('industirx-cme-opt3')
    for entry in volume.listdir('/reports'):
        if entry.type.name != 'FILE': continue
        target = reports/Path(entry.path).name
        with target.open('wb') as stream:
            for block in volume.read_file(entry.path): stream.write(block)
    target = root/'data/test_factory_clip.mp4'
    target.parent.mkdir(exist_ok=True)
    if not target.exists():
        with target.open('wb') as stream:
            for block in volume.read_file('/factory.mp4'): stream.write(block)
    print('Measured benchmark reports and actual factory MP4 downloaded.')


if __name__ == '__main__': main()
