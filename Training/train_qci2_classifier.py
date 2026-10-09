"""Existing training-directory entry point for the QCI-2 local classifier."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from QCI_2_Defect_Classifier.train import main

if __name__=='__main__':raise SystemExit(main())
