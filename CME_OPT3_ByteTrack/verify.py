"""Capture actual regression and CLI validation output for the handoff."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / 'CME_OPT3_ByteTrack/reports'


def main():
    jobs = [
        ('cme2_tests.txt', ['-m', 'unittest', 'discover', '-s', 'Confidence_Calibration/tests', '-v']),
        ('sed1_tests.txt', ['-m', 'unittest', 'discover', '-s', 'SED_1_Multi_Camera/tests', '-v']),
        ('sed2_and_tracker_tests.txt', ['-m', 'unittest', 'discover', '-s', 'SED_2_Alert_Escalation/tests', '-v']),
        ('command_validation.txt', ['Backend/main.py', '--help']),
        ('compile_validation.txt', ['-m', 'compileall', '-q', 'Backend', 'Frontend',
          'CME_OPT3_ByteTrack', 'SED_1_Multi_Camera', 'SED_2_Alert_Escalation']),
    ]
    for name, command in jobs:
        result = subprocess.run([sys.executable, '-X', 'utf8', *command], cwd=ROOT,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8')
        (REPORTS/name).write_text(result.stdout + f'\nExit code: {result.returncode}\n', encoding='utf-8')
        print(name, result.returncode, flush=True)
        if result.returncode:
            raise SystemExit(result.returncode)


if __name__ == '__main__': main()
