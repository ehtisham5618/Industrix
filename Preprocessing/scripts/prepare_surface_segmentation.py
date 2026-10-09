"""Repository preprocessing entry point for the QCI-1 local typed pipeline."""
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from QCI_1_Surface_Defect_Segmentation.cli import main

if __name__=='__main__':raise SystemExit(main())
