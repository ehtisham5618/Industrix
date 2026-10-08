"""Export the existing model, deterministic training-only PTQ, and validated artifacts."""
from __future__ import annotations
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))

from ESE_CPU1_Quantization.export import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--weights',type=Path,default=ROOT/'Backend/best.pt')
    parser.add_argument('--data',type=Path,default=ROOT/'Hazard_Expansion/configs/12class_data.yaml')
    parser.add_argument('--calibration-images',type=int,default=300)
    parser.add_argument('--seed',type=int,default=42)
    parser.add_argument('--imgsz',type=int,choices=[640],default=640)
    parser.add_argument('--output-root',type=Path,default=ROOT/'Backend/weights')
    parser.add_argument('--skip-baseline',action='store_true',help='Require an existing identical-source baseline report')
    run(parser.parse_args())


if __name__=='__main__': main()
