"""Fast API tests and related existing pipeline regressions, separate from UI soak."""
from pathlib import Path
import json
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]

def main():
    out=ROOT/'IFE_UI1_Streamlit_Console/reports';out.mkdir(parents=True,exist_ok=True)
    results={}
    for name,path in [('console','IFE_UI1_Streamlit_Console/tests'),('sed1','SED_1_Multi_Camera/tests'),
                      ('sed2','SED_2_Alert_Escalation/tests'),('sed3','SED_3_Stress_Testing/tests')]:
        command=[sys.executable,'-m','unittest','discover','-s',path,'-v']
        run=subprocess.run(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        (out/(name+'_tests_terminal.txt')).write_text('Command: '+' '.join(command)+'\n'+run.stdout+'\nExit code: '+str(run.returncode)+'\n',encoding='utf-8')
        found=re.search(r'Ran (\d+) tests',run.stdout)
        results[name]=dict(count=int(found[1]) if found else 0,exit_code=run.returncode,passed=run.returncode==0)
        print(name,results[name],flush=True)
    run=subprocess.run([sys.executable,'Experiment_Tracking/scripts/validate_registry.py'],cwd=ROOT,
                       stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    (out/'registry_validation_terminal.txt').write_text(run.stdout+'\nExit code: '+str(run.returncode)+'\n',encoding='utf-8')
    results['registry']=dict(exit_code=run.returncode,passed=run.returncode==0)
    (out/'test_results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    if not all(r['passed'] for r in results.values()):raise SystemExit(1)

if __name__=='__main__':main()
