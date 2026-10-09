param(
    [string]$Remote = 'origin',
    [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $taskRoot
$taskBranch = 'feature/sprint2-qci3-severity-iot-alerts'
$taskBase = '9daaa97e0f3c674095ec98a79f8d215a18bc3b2e'
$taskCount = git -C $repoRoot rev-list --count "$taskBase..$taskBranch"
if ($LASTEXITCODE -ne 0 -or $taskCount -ne '2') { throw 'Expected exactly two saved QCI-3 commits.' }
$pushArguments = @('-C', $repoRoot, 'push', '--set-upstream')
if ($DryRun) { $pushArguments += '--dry-run' }
$pushArguments += @($Remote, $taskBranch)
& git @pushArguments
if ($LASTEXITCODE -ne 0) { throw 'Push failed; saved commits are intact. Check access/remote history before retrying.' }
