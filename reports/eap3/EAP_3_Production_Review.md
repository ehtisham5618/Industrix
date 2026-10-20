# EAP-3 — Lightweight Multi-Stage Dockerfile: Production Review

**Status: IMPLEMENTED — REVIEW BLOCKED** (all local gates pass; GitHub CI has never run on the repository).

## Image size (gate: unpacked filesystem < 1,800,000,000 bytes, decimal 1.8 GB)
| Image | Target | Unpacked (gate) | `docker image inspect .Size` | gzip `docker save` | Gate |
|---|---|---:|---:|---:|---|
| `industrix:eap3` | `bundled` (weights included) | **1,542,234,302 B** (1.542 GB / 1.436 GiB) | 484,175,201 B | 481,250,354 B | PASS (257.8 MB headroom) |
| `industrix:eap3-runtime` | `runtime` (weights mounted) | 1,507,953,786 B (1.508 GB) | 453,986,023 B | — | PASS |

Unpacked size is `du -sxb /` run as uid 0 in a fresh `--network none` container.
On this Docker Desktop (containerd image store) `.Size` reports **compressed**
content, and `docker image ls` "disk usage" (2.09 GB) adds compressed blobs to the
unpacked snapshot, so neither is used as the gate. The first measured build
(before optimisation) was 1,758,034,813 B unpacked, only 42 MB under the limit;
removing polars (unused by serving, see requirements file) gave the headroom above.

Largest contents: torch 695 MB, OpenVINO 184 MB, OpenCV headless 164 MB, SciPy 115 MB;
weights 22.5 MB (`best.pt`) + 12 MB (OpenVINO INT8).

## Verification (actual runs)
| Check | Result |
|---|---|
| Docker build (bundled + runtime) | PASS — exit 0, Docker 29.7.2 linux/amd64 |
| Size gate | PASS — bytes above |
| Container tests | PASS — 16 passed, 0 skipped (`pytest_container_output.txt`) |
| Non-root / no compilers | PASS — uid 10001; gcc, cc, g++, make absent |
| Health | PASS — `/health` 200, 12 classes, SHA256 `c4aba081…0061` |
| Real inference | PASS — `/predict` contract-valid via the EAP-2 gate; 3 identical repeats; corrupt upload → 400 |
| Memory | +1.20% container memory over 30 warmed requests |
| Offline | PASS — real `/predict` inside `--network none --read-only`; physical disconnection NOT VERIFIED |
| Missing / corrupt / wrong-checksum weights | PASS — container exits non-zero with a clear message |
| SIGTERM | PASS — exit 0, graceful shutdown |
| Repository suite | 507 passed, 2 failed (inherited ESE-CPU1 size/mAP gates) |
| EAP-2 suite | 29 passed (corrupt-upload defect now fixed) |
| Org PR gate (compileall + flake8 E9,F63,F7,F82) | PASS — 0 findings on 303 tracked files |
| CI workflow | NOT VERIFIED — Actions has not run on `devlogixtechnology/industrix` |

## Defects found and fixed while containerising
1. `/predict` returned 500 for corrupt uploads (EAP-2 finding); now 400.
2. Ultralytics' patched `Image.open` imports `pi-heif` after any failed open; offline images without it returned 500. `pi-heif` is pinned in the image and `/predict` also handles its absence.
3. Read-only root filesystem broke the shared `Backend/data/events.db` (incidents, QCI-3, QCI-4); it now lives on the `/data` volume.
4. A failed fail-fast startup left QCI-4 monitor threads running, so the container never exited; the monitor is now stopped first.

## Remaining blockers
- GitHub Actions never ran on the repository (container job unverified on CI).
- Physical network disconnection not tested.
- Camera video sources for `/streams/start` must be mounted; QCI-2 classifier weights are not bundled.
