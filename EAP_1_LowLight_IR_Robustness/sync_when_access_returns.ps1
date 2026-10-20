param([string]$Remote = 'origin', [switch]$DryRun)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $taskRoot
$taskBranch = 'feature/sprint3-eap1-lowlight-ir-robustness'
$taskBase = '93607fb873341710bfdc33f170f1cd49b1953e28'
$taskCount = git -C $repoRoot rev-list --count "$taskBase..$taskBranch"
if ($LASTEXITCODE -ne 0 -or $taskCount -ne '2') { throw 'Expected exactly two saved EAP-1 commits.' }
$pushArguments = @('-C', $repoRoot, 'push', '--set-upstream')
if ($DryRun) { $pushArguments += '--dry-run' }
$pushArguments += @($Remote, $taskBranch)
& git @pushArguments
if ($LASTEXITCODE -ne 0) { throw 'Push failed; saved commits are intact. Check access/remote history before retrying.' }
