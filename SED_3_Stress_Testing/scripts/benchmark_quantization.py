"""Batch1,640x640 CPU-only comparison of the current detector deployment formats."""
from __future__ import annotations
import argparse
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from ESE_CPU1_Quantization.benchmark import run


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--weights',type=Path,default=ROOT/'Backend/best.pt')
    parser.add_argument('--data',type=Path,default=ROOT/'Hazard_Expansion/configs/12class_data.yaml')
    parser.add_argument('--output',type=Path,default=ROOT/'SED_3_Stress_Testing/reports/quant_report.json')
    parser.add_argument('--output-root',type=Path,default=ROOT/'Backend/weights')
    parser.add_argument('--threads',type=int,default=None,help='Default: verified thread-profile selection,otherwise2')
    parser.add_argument('--warmup',type=int,default=30)
    parser.add_argument('--iterations',type=int,default=200)
    parser.add_argument('--skip-evaluation',action='store_true',help='Require existing matched held-out accuracy reports')
    run(parser.parse_args())


if __name__=='__main__':main()
