"""Sequential functional regressions; keep measured hardware gates explicit."""
import json
import re
import subprocess
import sys
from .prepare import ROOT,TASK

def main():
    out=TASK/'reports';out.mkdir(exist_ok=True);results={}
    command=[sys.executable,'-X','utf8','-m','pytest','tests/test_end_to_end_pipeline.py','-v','--durations=5']
    e2e=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
    terminal=e2e.stdout+e2e.stderr
    normalized='\n'.join(line.rstrip() for line in terminal.splitlines())
    (ROOT/'reports/IFE_UI3_E2E_Test_Result.txt').write_text('Command: '+subprocess.list2cmdline(command)+'\n'+normalized+'\nExit code: '+str(e2e.returncode)+'\n',encoding='utf-8')
    collected=re.search(r'collected (\d+) items',terminal);passed=re.search(r'(\d+) passed',terminal);duration=re.search(r'in ([\d.]+)s',terminal)
    results['e2e']=dict(collected=int(collected[1]) if collected else 0,passed_count=int(passed[1]) if passed else 0,
        passed=e2e.returncode==0,exit_code=e2e.returncode,duration_seconds=float(duration[1]) if duration else None,
        skipped=0 if ' skipped' not in terminal else None)
    print('e2e',results['e2e'],flush=True)
    groups=[('audit',['discover','-s','IFE_UI2_Incident_Audit/tests','-v']),('cme2',['discover','-s','Confidence_Calibration/tests','-v']),
        ('streams',['discover','-s','SED_1_Multi_Camera/tests','-v']),('tracking_severity',['discover','-s','SED_2_Alert_Escalation/tests','-v']),
        ('console',['discover','-s','IFE_UI1_Streamlit_Console/tests','-v']),
        ('quantization_functional',['ESE_CPU1_Quantization.tests.test_quantization.QuantizationCalculations',
          'ESE_CPU1_Quantization.tests.test_quantization.MeasuredQuantizationAcceptance.test_selected_artifact_hashes',
          'ESE_CPU1_Quantization.tests.test_quantization.MeasuredQuantizationAcceptance.test_openvino_int8_loads_and_runs_batch_one_on_cpu',
          'ESE_CPU1_Quantization.tests.test_quantization.MeasuredQuantizationAcceptance.test_fp16_onnx_loads_and_runs_batch_one_on_cpu','-v'])]
    for name,args in groups:
        run=subprocess.run([sys.executable,'-X','utf8','-m','unittest',*args],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
        text=run.stdout+run.stderr;count=re.search(r'Ran (\d+) tests in ([\d.]+)s',text)
        normalized='\n'.join(line.rstrip() for line in text.splitlines())
        (out/(name+'_tests.txt')).write_text(normalized+'\nExit code: '+str(run.returncode)+'\n',encoding='utf-8')
        results[name]=dict(collected=int(count[1]) if count else 0,duration_seconds=float(count[2]) if count else None,
            passed=run.returncode==0,exit_code=run.returncode)
        print(name,results[name],flush=True)
    results['scope_note']='Functional integration regressions. Existing CPU1 measured accuracy/size and CPU2/CPU3 throughput acceptance gates remain FAILED in their original evidence; this task does not retrain or requalify those hardware gates.'
    (out/'regression_results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    if not all(value['passed'] for value in results.values() if isinstance(value,dict)):raise SystemExit(1)

if __name__=='__main__':main()
