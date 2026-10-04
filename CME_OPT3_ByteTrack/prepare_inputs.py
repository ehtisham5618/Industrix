"""Cache the licensed source and upload sealed benchmark inputs to Modal."""
from pathlib import Path
import hashlib
import json
import modal
from Confidence_Calibration.scripts.download_commons_clips import commons_direct_url, download

ROOT = Path(__file__).resolve().parents[1]


def main():
    runtime = ROOT / 'CME_OPT3_ByteTrack/runtime'
    runtime.mkdir(parents=True,exist_ok=True)
    video = runtime/'Twentse_textielindustrie-948017.ogv'
    if not video.exists():
        download(commons_direct_url('File:Twentse textielindustrie-948017.ogv'),video)
    inputs = {'factory.ogv':video, 'best.pt':ROOT/'Backend/best.pt',
              'events.csv':ROOT/'CME_OPT3_ByteTrack/annotations/factory_events.csv'}
    hashes = {}
    for name,path in inputs.items():
        with path.open('rb') as stream: hashes[name] = hashlib.file_digest(stream,'sha256').hexdigest()
    assert hashes['best.pt'] == 'c4aba081f6357e23a7370a5f7cf98eff2c6faa0c4c20a2d4dcb8bcabdd490061'
    volume = modal.Volume.from_name('industirx-cme-opt3',create_if_missing=True)
    print('Uploading actual source, selected checkpoint and independently reviewed annotations',flush=True)
    with volume.batch_upload(force=True) as uploader:
        for name,path in inputs.items(): uploader.put_file(path,'/'+name)
    (runtime/'input_hashes.json').write_text(json.dumps(hashes,indent=2))
    print('Uploaded sealed benchmark inputs',hashes,flush=True)


if __name__ == '__main__': main()
