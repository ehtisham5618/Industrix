import json
import re
import subprocess
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
    out=ROOT/'IFE_UI2_Incident_Audit/reports';out.mkdir(parents=True,exist_ok=True);results={}
    for name,path in [('audit','IFE_UI2_Incident_Audit/tests'),('cme2','Confidence_Calibration/tests'),
        ('sed1','SED_1_Multi_Camera/tests'),('sed2_and_bytetrack','SED_2_Alert_Escalation/tests'),
        ('ui1','IFE_UI1_Streamlit_Console/tests')]:
        run=subprocess.run([sys.executable,'-X','utf8','-m','unittest','discover','-s',path,'-v'],cwd=ROOT,
            capture_output=True,text=True,encoding='utf-8')
        text=run.stdout+run.stderr;count=re.search(r'Ran (\d+) tests',text)
        (out/(name+'_tests.txt')).write_text('\n'.join(line.rstrip() for line in text.splitlines())+f'\nExit code: {run.returncode}\n',encoding='utf-8')
        results[name]=dict(tests=int(count[1]) if count else 0,passed=run.returncode==0)
        print(name,results[name],flush=True)
    (out/'test_results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    if not all(r['passed'] for r in results.values()):raise SystemExit(1)

if __name__=='__main__':main()
