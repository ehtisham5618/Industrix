param([switch]$DryRun)
$ErrorActionPreference = 'Stop'
$taskRepoRoot = Split-Path -Parent $PSScriptRoot
$taskBranch = 'feature/sprint2-qci1-surface-defect-segmentation'
git -C $taskRepoRoot rev-parse --verify "refs/heads/$taskBranch"
if ($LASTEXITCODE -ne 0) { throw 'Saved task branch missing; restore the verified bundle first.' }
$taskPushArgs = @('-C', $taskRepoRoot, 'push', '--set-upstream', 'origin', "${taskBranch}:${taskBranch}")
if ($DryRun) { $taskPushArgs += '--dry-run' }
& git @taskPushArgs
if ($LASTEXITCODE -ne 0) { throw 'Sync failed; check restored access and origin. No history was rewritten.' }
