param([string]$Remote = 'origin', [switch]$DryRun)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $taskRoot
$taskBranch = 'feature/sprint2-qci5-incident-pdf'
$taskBase = 'a11e10a917392a94d05645a0d7a55b5dd70bb9b0'
$taskCount = git -C $repoRoot rev-list --count "$taskBase..$taskBranch"
if ($LASTEXITCODE -ne 0 -or $taskCount -ne '2') { throw 'Expected exactly two saved QCI-5 commits.' }
$pushArguments = @('-C', $repoRoot, 'push', '--set-upstream')
if ($DryRun) { $pushArguments += '--dry-run' }
$pushArguments += @($Remote, $taskBranch)
& git @pushArguments
if ($LASTEXITCODE -ne 0) { throw 'Push failed; saved commits are intact. Check access/remote history before retrying.' }
