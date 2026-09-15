"""Required ESE-CPU3 entry point; implementation reuses SED-1/SED-3 components."""
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from ESE_CPU3_Soak_Test.soak import main

if __name__=='__main__':raise SystemExit(main())
