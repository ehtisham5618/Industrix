param([switch]$DryRun)
$ErrorActionPreference = 'Stop'
$taskRepoRoot = Split-Path -Parent $PSScriptRoot
$taskBranch = 'feature/atlantis-openvino-quant'
git -C $taskRepoRoot rev-parse --verify "refs/heads/$taskBranch"
if ($LASTEXITCODE -ne 0) { throw 'The saved task branch is missing. Restore the verified Git bundle first.' }
$taskPushArgs = @('-C', $taskRepoRoot, 'push', '--set-upstream', 'origin', "${taskBranch}:${taskBranch}")
if ($DryRun) { $taskPushArgs += '--dry-run' }
& git @taskPushArgs
if ($LASTEXITCODE -ne 0) {
    throw 'Sync failed. Check restored repository permission and the remote URL. No history was rewritten.'
}
