"""Preserve exactly two task commits and verify independent local recovery."""
from __future__ import annotations

import json
import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

from .config import ROOT
from .validation import file_hash

TASK = ROOT/'QCI_1_Surface_Defect_Segmentation'
BRANCH = 'feature/sprint2-qci1-surface-defect-segmentation'
BASE = '37f9dd64a5bfe2597cd2385896eb3b92c9652f29'


def git(args: list[str], cwd: Path = ROOT) -> str:
    """Run checked Git operations, without shell interpolation."""
    return subprocess.check_output(['git', *args], cwd=cwd, text=True, stderr=subprocess.STDOUT).strip()


def main() -> None:
    """Verify archive hashes, clone history, rerun real-mask import and local sync."""
    commits = git(['log', '--format=%H%x09%s', BASE+'..'+BRANCH]).splitlines()
    if len(commits) != 2: raise ValueError('Exactly two new QCI-1 commits are required')
    if git(['status', '--porcelain']): raise ValueError('Commit all task deliverables before backup')
    backup = TASK/'backups'; backup.mkdir(parents=True, exist_ok=True)
    bundle = backup/'QCI_1_complete_history.bundle'
    git(['bundle', 'create', str(bundle), '--all'])
    verification = git(['bundle', 'verify', str(bundle)])
    (backup/'bundle_verification.txt').write_text(verification+'\n', encoding='utf-8')
    head = git(['rev-parse', BRANCH])
    probe = TASK/'runtime'/('restore_probe_'+head[:7])
    if probe.exists(): raise ValueError('Existing restore probe preserved; use a fresh HEAD')
    git(['clone', '--quiet', '--branch', BRANCH, str(bundle), str(probe)])
    assert git(['rev-parse', 'HEAD'], probe) == head
    archive = backup/'QCI_1_local_datasets_and_runtime.zip'
    members: list[dict[str, Any]] = []
    inputs = [ROOT/'final_dataset', TASK/'runtime/segmentation_dataset', ROOT/'reports/qci1']
    original = TASK/'runtime/downloads/KolektorSDD.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as zipped:
        for directory in inputs:
            for path in directory.rglob('*'):
                if not path.is_file(): continue
                name = path.relative_to(ROOT).as_posix()
                zipped.write(path, name)
                members.append(dict(path=name, bytes=path.stat().st_size, sha256=file_hash(path)))
        name = original.relative_to(ROOT).as_posix(); zipped.write(original, name)
        members.append(dict(path=name, bytes=original.stat().st_size, sha256=file_hash(original)))
    print('Saved runtime archive, verifying every member:', len(members), flush=True)
    with zipfile.ZipFile(archive) as zipped:
        for member in members:
            with zipped.open(member['path']) as stream:
                assert hashlib.file_digest(stream, 'sha256').hexdigest() == member['sha256']
            if member['path'].startswith('QCI_1_Surface_Defect_Segmentation/runtime/segmentation_dataset/'):
                zipped.extract(member['path'], probe)
    # Recovered clone, recovered actual masks, newly generated output directory.
    config = probe/'QCI_1_Surface_Defect_Segmentation/runtime/restore_validation.yaml'
    config.write_text('dataset_root: QCI_1_Surface_Defect_Segmentation/runtime/segmentation_dataset\noutput_dir: QCI_1_Surface_Defect_Segmentation/runtime/restore_reports\nannotation_format: indexed_mask\nannotation_dir: masks\nannotation_extension: .png\nmax_annotation_bytes: 16000000\nwrite_processed: false\n', encoding='utf-8')
    run = subprocess.run([sys.executable, '-X', 'utf8', str(probe/'Preprocessing/scripts/prepare_surface_segmentation.py'), '--config', str(config)], cwd=probe, text=True, capture_output=True, encoding='utf-8')
    (backup/'restored_ingestion_output.txt').write_text(run.stdout+run.stderr+'\nExit: '+str(run.returncode), encoding='utf-8')
    assert run.returncode == 0
    restored = json.loads((probe/'QCI_1_Surface_Defect_Segmentation/runtime/restore_reports/dataset_manifest.json').read_text(encoding='utf-8'))
    expected = json.loads((ROOT/'reports/qci1/segmentation/dataset_manifest.json').read_text(encoding='utf-8'))
    assert restored['statistics'] == expected['statistics']
    # Exercise future push helper against a disposable LOCAL bare Git repository.
    bare = TASK/'runtime'/('sync_probe_'+head[:7]+'.git')
    git(['init', '--quiet', '--bare', str(bare)])
    git(['remote', 'set-url', 'origin', str(bare)], probe)
    pushed = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(probe/'QCI_1_Surface_Defect_Segmentation/sync_when_access_returns.ps1')], capture_output=True, text=True)
    assert pushed.returncode == 0, pushed.stdout+pushed.stderr
    assert git(['--git-dir', str(bare), 'rev-parse', BRANCH]) == head
    (backup/'local_sync_verification.txt').write_text(pushed.stdout+pushed.stderr, encoding='utf-8')
    delivery = dict(branch=BRANCH, base_commit=BASE, commits=commits, head=head,
        bundle=dict(path=bundle.relative_to(ROOT).as_posix(), sha256=file_hash(bundle), verified=True, restored_head_verified=True),
        runtime_archive=dict(path=archive.relative_to(ROOT).as_posix(), bytes=archive.stat().st_size, sha256=file_hash(archive), all_member_hashes_verified=True, members=members),
        restored_genuine_dataset_ingestion_verified=True, restored_samples=restored['statistics']['valid_segmentation_samples'],
        future_sync_script_verified_against_local_bare_repo=True, github_pushed=False, pr_created=False,
        original_remote=git(['remote', 'get-url', 'origin']), sync_command='powershell -ExecutionPolicy Bypass -File QCI_1_Surface_Defect_Segmentation/sync_when_access_returns.ps1')
    (backup/'delivery_manifest.json').write_text(json.dumps(delivery, indent=2)+'\n', encoding='utf-8')
    print('Verified complete history, all dataset/runtime bytes, restored ingestion and future local sync.')
    print('HEAD:', head, 'archive SHA256:', delivery['runtime_archive']['sha256'])


if __name__ == '__main__': main()
