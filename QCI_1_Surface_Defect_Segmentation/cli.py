"""Local entry point; explicit nonzero codes for blocked/partial dataset gates."""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from pathlib import Path

from .config import ROOT,load_config
from .errors import ConfigurationError
from .offline import no_network
from .pipeline import run
from .contracts import FatalResult


def main(argv: list[str] | None = None) -> int:
    """Run with TCP disabled; SUCCESS=0, fatal=1, BLOCKED=2, PARTIAL/FAILED=3."""
    parser=argparse.ArgumentParser(description='Validate actual local surface annotations and prepare genuine segmentation pairs')
    parser.add_argument('--config',type=Path,default=ROOT/'QCI_1_Surface_Defect_Segmentation/configs/qci1_segmentation.yaml')
    args=parser.parse_args(argv);logging.basicConfig(level=logging.INFO,format='%(message)s')
    try:
        with no_network() as audit:
            result=run(load_config(args.config),offline_verified=True)
            if audit.attempts:raise ConfigurationError('Unexpected runtime network connection attempt')
        stats=result.statistics
        print(result.model_dump_json(indent=2))
        print(f'Dataset audit complete: {stats.total_samples} images, source valid={stats.source_valid_samples}, source invalid={stats.invalid_source_samples}, genuine segmentation valid={stats.valid_segmentation_samples}')
        print('Status:',result.status,'Manifest:',result.manifest_path)
        return {'SUCCESS':0,'BLOCKED':2,'PARTIAL':3,'FAILED':3}[result.status]
    except (ConfigurationError,OSError,ValueError,sqlite3.Error) as exc:
        print(FatalResult(error_type=type(exc).__name__,message=str(exc)[:1000]).model_dump_json())
        return 1


if __name__=='__main__':raise SystemExit(main())
