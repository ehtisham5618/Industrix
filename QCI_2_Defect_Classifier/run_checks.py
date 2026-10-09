"""Capture actual focused QCI-2/QCI-1 regression and complete-root test results."""
from __future__ import annotations
import json
from .common import REPORTS
from QCI_1_Surface_Defect_Segmentation.run_checks import pytest_run


def main() -> int:
    """Never hide old failures, skip numeric gates or fabricate collected counts."""
    focused=pytest_run(['tests/test_qci2_classifier.py','tests/test_qci2_dataset_adapter.py','tests/test_qci2_registry.py','-q','--durations=5'],REPORTS/'pytest_output.txt')
    print('QCI-2 focused:',focused,flush=True)
    dependency=pytest_run(['tests/test_qci1_ingestion.py','tests/test_qci1_additional_edges.py','tests/test_qci1_decoder_isolation.py','tests/test_qci1_acquisition.py','-q'],REPORTS/'qci1_regression_output.txt')
    print('QCI-1 regression:',dependency,flush=True)
    complete=pytest_run(['-q'],REPORTS/'repository_pytest_output.txt')
    print('Complete repository:',complete,flush=True)
    (REPORTS/'test_results.json').write_text(json.dumps(dict(qci2=focused,qci1=dependency,repository=complete,scope_note='Full-root prior quantitative failures are visible and unmodified.'),indent=2)+'\n',encoding='utf-8')
    return 0 if focused['exit_code']==0 and dependency['exit_code']==0 else 1


if __name__=='__main__':raise SystemExit(main())
