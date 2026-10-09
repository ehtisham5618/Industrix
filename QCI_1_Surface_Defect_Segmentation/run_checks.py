"""Record actual focused and complete-repository pytest results separately."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from .config import ROOT


def pytest_run(args: list[str], output: Path) -> dict[str, Any]:
    """Capture normalized terminal output without hiding failures or skips."""
    command=[sys.executable,'-X','utf8','-m','pytest',*args]
    run=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
    text=run.stdout+run.stderr
    output.write_text('Command: '+subprocess.list2cmdline(command)+'\n'+'\n'.join(line.rstrip() for line in text.splitlines())+'\nExit code: '+str(run.returncode)+'\n',encoding='utf-8')
    counts={kind:int(match[1]) if (match:=re.search(r'(\d+) '+kind,text)) else 0 for kind in ('passed','failed','skipped','error')}
    duration=re.search(r'in ([\d.]+)s',text)
    return dict(command=command,exit_code=run.returncode,passed=counts['passed'],failed=counts['failed'],skipped=counts['skipped'],
        errors=counts['error'],collected=None if 'Interrupted:' in text else sum(counts.values()),duration_seconds=float(duration[1]) if duration else None)


def main() -> int:
    """Focused code gate is mandatory; repository baseline failures stay visible."""
    out=ROOT/'reports/qci1';out.mkdir(parents=True,exist_ok=True)
    focused=pytest_run(['tests/test_qci1_ingestion.py','tests/test_qci1_additional_edges.py','tests/test_qci1_decoder_isolation.py','tests/test_qci1_acquisition.py','-q','--durations=5'],out/'pytest_output.txt')
    print('QCI focused:',focused,flush=True)
    complete=pytest_run(['-q'],out/'repository_pytest_output.txt')
    print('Complete repository:',complete,flush=True)
    report=dict(qci=focused,repository=complete,scope_note='Full repository acceptance failures are preserved. Do not weaken old tests or present this result as an all-green repository.')
    (out/'test_results.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return 0 if focused['exit_code']==0 else 1


if __name__=='__main__':raise SystemExit(main())
