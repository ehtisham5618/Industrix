"""Execute final acceptance commands and preserve real stdout, stderr and exit codes."""
import json,os,subprocess,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
REPORTS=ROOT/'CME_OPT1_Hard_Negative_Augmentation/reports'
SOURCE='Hazard_Expansion/content_runtime/combined_dataset_reviewed_v3_final'
OUTPUT='Hazard_Expansion/content_runtime/combined_dataset_augmented_v3'
SELECTION='CME_OPT1_Hard_Negative_Augmentation/reports/reviewed_selection_v3.csv'
R='CME_OPT1_Hard_Negative_Augmentation/reports'

def run(args,log):
    command=[sys.executable,*args]
    with (REPORTS/log).open('w',encoding='utf-8',newline='\n') as f:
        f.write('Executed: '+subprocess.list2cmdline(command)+'\n\n');f.flush()
        result=subprocess.run(command,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,
            env={**os.environ,'PYTHONIOENCODING':'utf-8'})
        f.write(f'\nExit code: {result.returncode}\n')
    # Preserve the text while rendering terminal carriage returns as portable LF lines.
    path=REPORTS/log
    path.write_text('\n'.join(line.rstrip() for line in path.read_text(encoding='utf-8').splitlines())+'\n',encoding='utf-8',newline='\n')
    print(f'{log}: exit {result.returncode}',flush=True)
    if result.returncode:raise SystemExit(result.returncode)

def main():
    run(['CME_OPT1_Hard_Negative_Augmentation/scripts/build_reference_evidence.py'],'reference_evidence_terminal_output.txt')
    run(['Preprocessing/scripts/augment_hard_negatives.py','--dataset',SOURCE,'--output',OUTPUT,
        '--manifest',SELECTION,'--reports',R,'--seed','42','--count','300','--version','combined-12class-v3-hardnegative'],
        'augmentation_terminal_output.txt')
    run(['Preprocessing/scripts/validate_yolo_dataset.py','--dataset',OUTPUT,'--report',R+'/after/validation.json'],
        'validation_terminal_output.txt')
    run(['Preprocessing/scripts/dataset_statistics.py','--dataset',OUTPUT,'--output',R+'/after'],
        'statistics_terminal_output.txt')
    run(['CME_OPT1_Hard_Negative_Augmentation/scripts/build_report.py','--source',SOURCE,'--dataset',OUTPUT,
        '--selection',SELECTION],'report_terminal_output.txt')
    run(['-m','unittest','discover','-s','CME_OPT1_Hard_Negative_Augmentation/tests','-v'],'tests_terminal_output.txt')
    status=json.loads((REPORTS/'completion_status.json').read_text())
    if status['overall']!='PASS':raise SystemExit('Acceptance gate did not pass')
    print(json.dumps(status,indent=2),flush=True)

if __name__=='__main__':main()
