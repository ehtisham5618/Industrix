"""Preserve native stdout/stderr and true exit status across Windows shells."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('command',nargs=argparse.REMAINDER)
    args=parser.parse_args()
    command=args.command[1:] if args.command and args.command[0]=='--' else args.command
    if not command: parser.error('Supply a command after --')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('w',encoding='utf-8') as log:
        log.write('Command: '+json.dumps(command)+'\n');log.flush()
        code=subprocess.call(command,stdout=log,stderr=subprocess.STDOUT)
        log.write(f'\nExit code: {code}\n')
    print(f'Exit code: {code}; terminal evidence: {args.output}',flush=True)
    return code

if __name__=='__main__': sys.exit(main())
