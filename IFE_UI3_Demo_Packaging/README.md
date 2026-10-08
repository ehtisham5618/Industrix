# IFE-UI3 - Sprint 4 local demo packaging

This task integrates the existing components without training a new model.
Use the backend virtual environment from ESE-CPU1. The Streamlit interpreter
on this workstation is `C:\Python314\python.exe`; the launcher passes all paths
through configuration/environment, without editing application Python files.
The organization has revoked repository access: all work is saved locally.

## Prepare and verify

From the repository root in PowerShell:

```powershell
$taskPython = '.\ESE_CPU1_Quantization\runtime\venv\Scripts\python.exe'
& $taskPython -m IFE_UI3_Demo_Packaging.prepare
& $taskPython -m IFE_UI3_Demo_Packaging.check_readiness
& $taskPython -m pytest tests/test_end_to_end_pipeline.py -v
& $taskPython -m IFE_UI3_Demo_Packaging.run_checks
& $taskPython -m IFE_UI3_Demo_Packaging.run_local_demo
```

Open <http://127.0.0.1:8501> and click **Start three feeds**. The guarded
launcher binds both servers to loopback, allows local IPC, and rejects external
Python TCP connections in both processes. Ctrl+C stops only its own children.
Install requirements before entering offline mode; the runtime never installs
or downloads anything. Readiness checks fail if ports 8000/8501 are occupied.

Individual commands remain supported. In a backend PowerShell window:

```powershell
$env:CAMERA_CONFIG='IFE_UI3_Demo_Packaging/configs/demo.json'
$env:INCIDENT_DATABASE='IFE_UI3_Demo_Packaging/runtime/demo/events.db'
$env:INCIDENT_SNAPSHOTS='IFE_UI3_Demo_Packaging/runtime/demo/snapshots'
$env:INFERENCE_ENGINE='openvino'
$env:IFE_UI3_DEMO='true'
& '.\ESE_CPU1_Quantization\runtime\venv\Scripts\python.exe' -m IFE_UI3_Demo_Packaging.offline_server
```

In a second window, set the same environment values and run:

```powershell
streamlit run Frontend/app.py --server.port 8501 --server.address 127.0.0.1 --browser.gatherUsageStats false
```

That standard frontend command is verified by the previous UI tasks. To apply
the explicit external-TCP guard to the frontend too, use the launcher's exact
frontend command:

```powershell
& 'C:\Python314\python.exe' -m IFE_UI3_Demo_Packaging.offline_server --frontend
```

## Reproducible footage and real inference

The optional demo configuration preserves the CPU2 schema, camera IDs and roles,
ring capacity 15 and every-fourth-frame sampler. Camera 01 repeats an existing
textile dataset image, letterboxed to 640x640. Camera 02 shows black standby for
75 seconds, then repeats an existing fire dataset image. Camera 03 uses a
640x360 derivative of the original local worker video at its original cadence.
These smaller demo sources reduce decode overhead during HD recording; the
original three-source configuration and its benchmark evidence are unchanged.
Images are tracked test fixtures; generated video, incident DB and crops are
ignored runtime data. Provenance, hashes and measured fixture predictions are in
`reports/fixture_provenance.json` and `reports/textile_provenance.json`.

These images come from the existing training archive. They establish deterministic
integration behavior, not held-out accuracy, installed factory coverage or new
workplace incidents. All predictions, IDs, confidence, candidate progress,
confirmation and SED-2 actions come from the actual production pipeline.
Thresholds, weights and the strict 15-observation rule are unchanged. Demo
incidents and PDFs are marked SAMPLE / DEMONSTRATION. Forklift proximity remains
unsupported. The original three-source configuration remains available.

## Recording and distribution

```powershell
& '.\ESE_CPU1_Quantization\runtime\venv\Scripts\python.exe' -m IFE_UI3_Demo_Packaging.record_demo
```

The recorder uses a fresh headless Edge browser, records its actual 1920x1080
viewport, drives normal Streamlit controls and downloads the actual PDF. It
rehearses a real incident, restarts the backend with the same DB, re-exports the
persisted incident and benchmarks the warmed three-feed pipeline before capture.
FFmpeg trims initial browser loading and encodes H.264; it adds no fake overlay,
static metrics, retiming or injected detection. The complete final video is
decoded again for validation. The walkthrough is silent; narration is optional.

Final local file:
`runtime/Atlantis_Sprint4_CPU_Ready_Demo_v0.4.0.mp4`.
Upload is **MANUAL ACTION REQUIRED**: upload this file to Google Drive, enable
the appropriate reviewer link access, and place the actual returned URL in the
agenda and prepared PR description. No connected authenticated Drive/Loom/YouTube
upload capability is available in this session. No share URL is invented.

## Local history and later sync

Branch: `feature/atlantis-demo-packaging`, based on UI2 commit
`bfbc4e6d6f07e3f4606f4b7d90852b64e4e3b015`. It includes all completed dependent
task branches; the cached main branch lacks this integrated work. Exactly two
new task commits use the established `IFE-UI3: ...` convention and the requested
Git author. No push, PR, merge or release tag occurs while access is revoked.

After access returns:

```powershell
.\IFE_UI3_Demo_Packaging\sync_when_access_returns.ps1
```

This performs an ordinary named-branch push, preserving the full dependent
history. It does not force-push or change another branch. Then submit the prepared
PR, satisfy reviewer/branch protection requirements and merge through the normal
repository process. Only the actual approved merged commit may receive the
annotated `v0.4.0-sprint4-cpu-ready` tag; no tag is created here.

`offline_backup.py` makes a verified complete-history Git bundle and a separate
hash/CRC-checked runtime ZIP including model files, source clips, recording and a
consistent SQLite online backup. The ignored `backups/delivery_manifest.json`
records the exact two commits, archive hashes and restore verification. Recovery:

```powershell
git clone -b feature/atlantis-demo-packaging IFE_UI3_Demo_Packaging/backups/IFE_UI3_complete_history.bundle recovered-industirx
```

Extract `IFE_UI3_local_runtime.zip` into that clone, recreate dependencies from
the existing requirements, and restore the GitHub origin with
`git remote set-url origin https://github.com/devlogixtechnology/industirx.git`.
The required packages are recorded in the readiness report. Virtual environments
are workstation-specific and are not archived. Keep the two recovery files on
separate storage if protection against loss of this entire disk is needed.
