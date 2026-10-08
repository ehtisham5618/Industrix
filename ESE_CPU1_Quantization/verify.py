"""Record functional/regression results and genuine measured acceptance failures."""
import io
import json
from pathlib import Path
import unittest

from .common import ROOT,REPORTS,write_json


def main():
    batches=[('quantization_tests','ESE_CPU1_Quantization/tests'),
             ('sed3_regression_tests','SED_3_Stress_Testing/tests')]
    records={}
    allowed={'test_actual_ir_size_below_6_5_decimal_mb','test_actual_map_drop_below_one_percentage_point'}
    for name,directory in batches:
        stream=io.StringIO()
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(
            unittest.defaultTestLoader.discover(str(ROOT/directory)))
        (REPORTS/f'{name}.txt').write_text(stream.getvalue(),encoding='utf-8')
        records[name]=dict(run=result.testsRun,passed=result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
            failed=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),
            failures=[test.id() for test,_ in result.failures])
        assert not result.errors,stream.getvalue()
        assert all(test.id().rsplit('.',1)[-1] in allowed for test,_ in result.failures),stream.getvalue()
        if name=='sed3_regression_tests':assert result.wasSuccessful(),stream.getvalue()
    write_json(REPORTS/'test_results.json',records)
    print(json.dumps(records,indent=2))


if __name__=='__main__':main()
