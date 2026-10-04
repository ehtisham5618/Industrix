"""Copy sealed inputs, then replace this process with the benchmark interpreter.

The same PID is watched during cold storage reads and during inference.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys


def main():
    hashes = json.loads(sys.argv[1])
    local = Path('/tmp/cme_opt3')
    local.mkdir(exist_ok=True)
    for name, expected in hashes.items():
        shutil.copy2(Path('/work')/name,local/name)
        with (local/name).open('rb') as f:
            assert hashlib.file_digest(f,'sha256').hexdigest() == expected
    args = [sys.executable,'-u','-m','CME_OPT3_ByteTrack.benchmark',
        '--video',str(local/'factory.mp4'),'--events',str(local/'events.csv'),'--weights',str(local/'best.pt'),
        '--output','/work/reports','--device','0','--duration','600','--evaluated-fps','10','--realtime']
    os.execv(sys.executable,args)


if __name__ == '__main__': main()
