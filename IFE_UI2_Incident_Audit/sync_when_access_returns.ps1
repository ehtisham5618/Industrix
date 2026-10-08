param([switch]$DryRun)
$ErrorActionPreference = 'Stop'
$taskRepoRoot = Split-Path -Parent $PSScriptRoot
$taskBranch = 'feature/atlantis-incident-pdf'
git -C $taskRepoRoot rev-parse --verify "refs/heads/$taskBranch"
if ($LASTEXITCODE -ne 0) { throw 'Saved task branch is missing. Restore the verified bundle first.' }
$taskPushArgs = @('-C', $taskRepoRoot, 'push', '--set-upstream', 'origin', "${taskBranch}:${taskBranch}")
if ($DryRun) { $taskPushArgs += '--dry-run' }
& git @taskPushArgs
if ($LASTEXITCODE -ne 0) { throw 'Sync failed. Check restored access/origin. No history was rewritten.' }
