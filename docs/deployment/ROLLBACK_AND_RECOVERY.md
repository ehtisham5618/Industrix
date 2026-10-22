# IndustriX Rollback and Recovery

Version 1.0.0 (FDD-3). There is **no automated rollback or artifact registry service**: rollback is a
manual procedure using Git revisions, the approved model file and its SHA256, and backups of local data.
Automation is a follow-up item.

## Preconditions
Repository access (`git`), write access to the deployment directory, the approved `best.pt`
(SHA256 `c4aba081…0061`) kept outside the deployment, and an operator able to stop/start the watchdog.

## 1. Identify the last known-good revision
- Each change arrives as a reviewed PR into `staging`; the merge commit or the PR head SHA is the revision.
- `git log --oneline -20` and the PR list identify candidates; the known-good revision is the last one
  whose FDD-1 release gate and smoke test passed (keep their reports).
- Model lineage: `Experiment_Tracking/model_registry.csv` (versions, SHA256) and
  `EAP_2_CI_Model_Regression/baselines/` (approved baseline manifest).

## 2. Preserve evidence and data first
```powershell
$stamp = Get-Date -Format yyyyMMdd-HHmmss; $dest = "..\industrix-backup-$stamp"; New-Item -ItemType Directory $dest
& $py -m EAP_5_Watchdog stop                                   # consistent copy: stop writers first
& $py -c "import sqlite3; s=sqlite3.connect('Backend/data/events.db'); d=sqlite3.connect(r'$dest\events.db'); s.backup(d)"
Copy-Item -Recurse EAP_5_Watchdog/runtime, data/snapshots, reports/incidents $dest -ErrorAction SilentlyContinue
Copy-Item EAP_5_Watchdog/configs/watchdog.json, Confidence_Calibration/configs/calibrated_thresholds.yaml $dest
git rev-parse HEAD > "$dest\revision.txt"
```
Never delete incident records, snapshots or model files during recovery.

## 3. Roll back the application
```powershell
git fetch origin
git checkout <known-good-sha>                                   # detached checkout of the approved revision
& $py -m pip install -r requirements.txt -r Frontend/requirements.txt   # only if requirements changed
& $py -m FDD_3_Deployment_Handoff.validate_deployment --expect-ports-free
& $py -m EAP_5_Watchdog start; & $py -m FDD_3_Deployment_Handoff.smoke_test
```
Container: re-run the previously approved image tag (`docker run ... industrix:<approved-tag>`); keep the
`industrix-data` volume, which holds `/data/events.db`.

## 4. Roll back a model or configuration
- Model: replace `Backend/best.pt` only with an approved file whose SHA256 matches the registry entry,
  keeping the current file renamed beside it (`best.pt.rejected-<date>`). Set `INDUSTRIX_MODEL_SHA256`
  to the approved hash so a wrong file cannot start.
- The class map must stay identical (12 classes, same order): `python -m FDD_2_Hardware_Taxonomy.taxonomy`
  must print CONSISTENT; the EAP-2 runner (`python -m EAP_2_CI_Model_Regression.runner`) re-checks
  hash, class map, contract and metrics against the approved baseline.
- Configuration: restore the backed-up JSON/YAML; validate with `python -m EAP_5_Watchdog validate`.

## 5. Verify recovery
Preflight PASS → `status` both healthy → smoke test PASS → (release) FDD-1 gate with no new failures.
Compare `/health` `model_sha256` with the approved hash.

## 6. Avoid restarting into a known-bad state
- Do not `start` the watchdog on a revision that failed validation; the watchdog will otherwise spend its
  restart budget and go `degraded`.
- Keep the failing revision SHA and reports in the backup folder; note it in the handoff log.

## 7. Escalate instead of retrying when
the approved model hash cannot be found; the incident database fails `PRAGMA integrity_check`; validation
fails on the known-good revision (environment problem); or the service is `degraded` again after one rollback.
