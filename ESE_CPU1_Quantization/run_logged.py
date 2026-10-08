"""Capture real command output without PowerShell encoding/redirection ambiguity."""
import argparse
from pathlib import Path
import subprocess
import sys


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--log',required=True,type=Path)
    parser.add_argument('command',nargs=argparse.REMAINDER)
    args=parser.parse_args()
    command=args.command
    if command and command[0]=='--':command=command[1:]
    args.log.parent.mkdir(parents=True,exist_ok=True)
    with args.log.open('w',encoding='utf-8') as stream:
        process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
            text=True,encoding='utf-8',errors='replace',bufsize=1)
        for line in process.stdout:
            stream.write(line);stream.flush();print(line,end='',flush=True)
        code=process.wait()
        stream.write(f'\nExit code: {code}\n')
    raise SystemExit(code)


if __name__=='__main__':main()
