"""FDD-4 reproducible product demo recording of the REAL IndustriX application.

python -m FDD_4_Demo.record_demo [--out-dir reports/fdd4/demo] [--name industrix_demo] [--dry-run]

Starts the real backend + dashboard through the EAP-5 watchdog, drives the real Streamlit UI in a
headless Microsoft Edge (Playwright) at 1920x1080 with live screen recording, uploads bundled local
fixtures for real inference, and exports an H.264 MP4 with ffmpeg. Caption cards are local HTML with
factual text only. Nothing is sped up; no detections are drawn by this script.

Exit codes: 0 recorded and verified; 1 recording or verification failed; 2 preflight failed.
Existing recordings are never overwritten (names are timestamped).
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path(__file__).resolve().parent / "demo_manifest.json"
BACKEND, DASHBOARD = "http://127.0.0.1:8000", "http://127.0.0.1:8501"
LOOPBACK = {"127.0.0.1", "localhost", "::1"}


class DemoError(RuntimeError):
    """Actionable failure; the message says what to fix."""


@dataclass
class SceneRecord:
    scene: int
    title: str
    start_s: float
    end_s: Optional[float] = None
    observed: dict = field(default_factory=dict)


def load_manifest(path: Path = MANIFEST) -> dict:
    if not path.is_file():
        raise DemoError(f"demo manifest not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DemoError(f"demo manifest is not valid JSON: {exc}") from exc
    for key in ("product", "resolution", "fps", "assets", "scenes"):
        if key not in data:
            raise DemoError(f"demo manifest missing '{key}'")
    width, height = data["resolution"]
    if (width, height) != (1920, 1080) or not 10 <= data["fps"] <= 60:
        raise DemoError("manifest must request 1920x1080 and 10-60 fps")
    ids = [s["id"] for s in data["scenes"]]
    if len(ids) != len(set(ids)) or not ids:
        raise DemoError("scene ids must be unique and non-empty")
    for scene in data["scenes"]:
        if scene.get("asset") and scene["asset"] not in data["assets"]:
            raise DemoError(f"scene {scene['id']} references unknown asset {scene['asset']}")
        if not 1 <= scene.get("hold_seconds", 0) <= 60:
            raise DemoError(f"scene {scene['id']} hold_seconds must be 1-60")
    return data


def preflight(manifest: dict, which: Callable[[str], Optional[str]] = shutil.which) -> dict:
    """Verify tools, browser, model and assets before anything starts. Raises DemoError."""
    problems = []
    tools = {name: which(name) for name in ("ffmpeg", "ffprobe")}
    problems += [f"{name} not found on PATH (install ffmpeg; it is not downloaded automatically)" for name, p in tools.items() if not p]
    try:
        import playwright  # noqa: F401
    except ImportError:
        problems.append("playwright not installed in this interpreter")
    model = ROOT / "Backend" / "best.pt"
    if not model.is_file():
        problems.append("Backend/best.pt missing: provision the approved checkpoint (never downloaded)")
    for name, rel in manifest["assets"].items():
        if not (ROOT / rel).is_file():
            problems.append(f"asset '{name}' missing: {rel}")
    if problems:
        raise DemoError("preflight failed: " + "; ".join(problems))
    return dict(tools=tools, model_bytes=model.stat().st_size)


def safe_output(out_dir: Path, name: str, stamp: str) -> Path:
    """Timestamped, never-overwriting output path inside out_dir."""
    if not name.replace("_", "").replace("-", "").isalnum():
        raise DemoError("output name may contain only letters, digits, '-' and '_'")
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{name}_{stamp}.mp4"
    if target.exists():
        raise DemoError(f"refusing to overwrite existing recording {target}")
    return target


def card_html(title: str, lines: list[str], kicker: str = "IndustriX") -> str:
    body = "".join(f"<p>{html.escape(line)}</p>" for line in lines)
    return (f"<!doctype html><html><head><meta charset='utf-8'><style>"
            "html,body{margin:0;height:100%;background:#0d1b2a;color:#e0e6ed;font-family:'Segoe UI',system-ui,sans-serif}"
            "main{height:100%;display:flex;flex-direction:column;justify-content:center;padding:0 160px}"
            "small{letter-spacing:.3em;text-transform:uppercase;color:#4cc9f0;font-size:22px}"
            "h1{font-size:72px;margin:18px 0 28px;font-weight:600}p{font-size:32px;margin:10px 0;color:#c8d3df;max-width:1500px}"
            f"</style></head><body><main><small>{html.escape(kicker)}</small><h1>{html.escape(title)}</h1>{body}</main></body></html>")


def settle(page, extra_ms: int = 2500) -> None:
    """Let Streamlit finish its incremental rendering (skeletons, icon font) before a scene is held."""
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:  # Streamlit keeps a websocket open; networkidle may not be reached
        pass
    page.wait_for_timeout(extra_ms)


def run(cmd: list[str], timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)


def wait_healthy(timeout: float = 240) -> float:
    started = time.monotonic()
    status = ROOT / "EAP_5_Watchdog" / "runtime" / "status.json"
    while time.monotonic() - started < timeout:
        try:
            data = json.loads(status.read_text(encoding="utf-8"))
            if data.get("running") and all(s["state"] == "healthy" for s in data["services"]):
                return time.monotonic() - started
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(2)
    raise DemoError(f"services not healthy within {timeout}s; see EAP_5_Watchdog/runtime/logs/")


def ffprobe(path: Path) -> dict:
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration,size:stream=codec_type,codec_name,width,height,r_frame_rate",
               "-of", "json", str(path)], 60)
    if out.returncode:
        raise DemoError(f"ffprobe failed: {out.stderr.strip()[:300]}")
    return json.loads(out.stdout)


def record(manifest: dict, out_dir: Path, name: str, python: str) -> dict:
    from playwright.sync_api import sync_playwright
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = safe_output(out_dir, name, stamp)
    work = ROOT / "FDD_4_Demo" / "runtime" / stamp
    work.mkdir(parents=True, exist_ok=False)
    start = run([python, "-m", "EAP_5_Watchdog", "start"], 120)
    if start.returncode:
        raise DemoError(f"watchdog start failed ({start.returncode}): {start.stdout.strip()[-300:]}")
    scenes: list[SceneRecord] = []
    blocked: list[str] = []
    try:
        startup_s = wait_healthy()
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True,
                                        args=["--disable-background-networking", "--disable-component-update"])
            context = browser.new_context(viewport=dict(width=1920, height=1080), device_scale_factor=1,
                                          record_video_dir=str(work), record_video_size=dict(width=1920, height=1080))

            def guard(route):  # offline guard: only file:, data:, blob: and loopback are allowed
                url = route.request.url
                host = urlparse(url).hostname
                if url.startswith(("file:", "data:", "blob:")) or host in LOOPBACK:
                    route.continue_()
                else:
                    blocked.append(url[:200])
                    route.abort()
            context.route("**/*", guard)
            page = context.new_page()
            t0 = time.monotonic()
            frames: list[str] = []

            def keyframe(index):  # a screenshot of the live page: the recorder clock drifts from the video timeline
                shot = out_dir / f"frame_{stamp}_scene{index:02d}.png"
                page.screenshot(path=str(shot))
                frames.append(str(shot.relative_to(ROOT)))
            for index, scene in enumerate(manifest["scenes"], 1):
                record_ = SceneRecord(index, scene["title"], round(time.monotonic() - t0, 2))
                kind = scene["kind"]
                if kind == "card":
                    card = work / f"card_{index}.html"
                    card.write_text(card_html(scene["title"], scene["lines"], scene.get("kicker", manifest["product"])), encoding="utf-8")
                    page.goto(card.as_uri())
                elif kind == "dashboard":
                    page.goto(DASHBOARD, wait_until="domcontentloaded")
                    page.get_by_role("button", name="Start three feeds").wait_for(timeout=60000)
                    settle(page)
                elif kind == "inference":
                    page.goto(DASHBOARD, wait_until="domcontentloaded")
                    page.get_by_role("button", name="Start three feeds").wait_for(timeout=60000)  # app fully rendered
                    settle(page, 1000)
                    page.get_by_role("tab", name="Image Inference").click()
                    page.get_by_text("Upload an image (JPG, JPEG, PNG)").first.wait_for(timeout=60000)
                    page.locator("input[type=file]").first.set_input_files(str(ROOT / manifest["assets"][scene["asset"]]),
                                                                           timeout=60000)
                    page.get_by_role("button", name="Detect Defects").wait_for(timeout=60000)
                    clicked = time.monotonic()
                    page.get_by_role("button", name="Detect Defects").click()
                    page.get_by_text("Detection Results").wait_for(timeout=90000)
                    record_.observed["click_to_results_s"] = round(time.monotonic() - clicked, 2)
                    record_.observed["count_text"] = page.get_by_text("Defects detected:").first.inner_text()
                    table = page.locator("table").last
                    table.wait_for(timeout=30000)  # wait until the results table has really rendered
                    record_.observed["table_text"] = table.inner_text()[:300]
                    page.get_by_text("Annotated result").first.scroll_into_view_if_needed()
                    page.wait_for_timeout(int(scene["hold_seconds"] * 500))  # first half: annotated image
                    table.scroll_into_view_if_needed()
                    page.wait_for_timeout(int(scene["hold_seconds"] * 500))  # second half: class/confidence table
                    keyframe(index)
                    record_.end_s = round(time.monotonic() - t0, 2)
                    scenes.append(record_)
                    print(f"scene {index}: {scene['title']} {record_.start_s}-{record_.end_s}s {record_.observed}", flush=True)
                    continue
                elif kind == "url":
                    page.goto(manifest["base_urls"][scene["target"]] + scene["path"], wait_until="load")
                    if scene.get("capture_text"):
                        record_.observed["page_text"] = page.inner_text("body")[:400]
                elif kind == "incidents":
                    page.goto(DASHBOARD, wait_until="domcontentloaded")
                    page.get_by_text("Industrial Vision Console").first.wait_for(timeout=60000)
                    page.get_by_role("button", name="Start three feeds").wait_for(timeout=60000)
                    heading = page.get_by_text(scene.get("anchor_text", "Incident"), exact=False).first
                    heading.wait_for(timeout=60000)
                    settle(page)
                    heading.scroll_into_view_if_needed()
                else:
                    raise DemoError(f"unknown scene kind {kind}")
                page.wait_for_timeout(int(scene["hold_seconds"] * 1000))
                keyframe(index)
                record_.end_s = round(time.monotonic() - t0, 2)
                scenes.append(record_)
                print(f"scene {index}: {scene['title']} {record_.start_s}-{record_.end_s}s {record_.observed or ''}", flush=True)
            video = page.video
            context.close()
            browser.close()
            webm = Path(video.path())
    finally:
        run([python, "-m", "EAP_5_Watchdog", "stop", "--timeout", "90"], 150)
    raw = work / "raw_capture.webm"
    webm.replace(raw)
    partial = target.with_suffix(".partial.mp4")
    enc = run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw), "-vf", "fps=30,scale=1920:1080",
               "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(partial)], 900)
    if enc.returncode or not partial.is_file():
        raise DemoError(f"ffmpeg export failed: {enc.stderr.strip()[:300]} (raw capture kept at {raw})")
    partial.replace(target)  # only a complete export gets the final name
    return dict(output=target, raw=raw, startup_s=startup_s, scenes=scenes, frames=frames, blocked=blocked, stamp=stamp)


def verify(path: Path, manifest: dict) -> dict:
    meta = ffprobe(path)
    video = next(s for s in meta["streams"] if s["codec_type"] == "video")
    duration = float(meta["format"]["duration"])
    checks = dict(exists=path.is_file() and path.stat().st_size > 0, width=video["width"], height=video["height"],
                  codec=video["codec_name"], fps=video["r_frame_rate"], duration_s=round(duration, 2),
                  audio=any(s["codec_type"] == "audio" for s in meta["streams"]), size_bytes=path.stat().st_size)
    decode = run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"], 600)
    checks["decodes_cleanly"] = decode.returncode == 0 and not decode.stderr.strip()
    checks["ok"] = checks["exists"] and (video["width"], video["height"]) == (1920, 1080) and checks["decodes_cleanly"]
    return checks


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out-dir", type=Path, default=ROOT / "reports" / "fdd4" / "demo")
    parser.add_argument("--name", default="industrix_demo")
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--python", default=sys.executable, help="interpreter with the full IndustriX stack")
    parser.add_argument("--dry-run", action="store_true", help="validate manifest and preflight only")
    args = parser.parse_args(argv)
    args.out_dir = args.out_dir.resolve()  # report paths are made relative to the repository root
    try:
        manifest = load_manifest(args.manifest)
        info = preflight(manifest)
    except DemoError as exc:
        print(f"PREFLIGHT FAILED: {exc}")
        return 2
    print(f"preflight ok: {len(manifest['scenes'])} scenes, tools {info['tools']}")
    if args.dry_run:
        return 0
    try:
        result = record(manifest, args.out_dir, args.name, args.python)
        checks = verify(result["output"], manifest)
    except DemoError as exc:
        print(f"RECORDING FAILED: {exc}")
        return 1
    except Exception as exc:  # e.g. a Playwright timeout: services were already stopped in record()'s finally
        print(f"RECORDING FAILED: {type(exc).__name__}: {str(exc).splitlines()[0][:300]} "
              "(services stopped; previous recordings untouched; partial capture left under FDD_4_Demo/runtime/)")
        return 1
    digest = hashlib.sha256(result["output"].read_bytes()).hexdigest()
    report = dict(task="FDD-4", recorded_at=result["stamp"], video=str(result["output"].relative_to(ROOT)), sha256=digest,
                  verification=checks, healthy_after_watchdog_start_s=round(result["startup_s"], 1),
                  scene_time_basis="recorder clock (seconds since the page opened); the video timeline drifts from it by a few seconds",
                  scenes=[asdict(s) for s in result["scenes"]], external_requests_blocked=result["blocked"],
                  keyframes=result["frames"], raw_capture=str(result["raw"].relative_to(ROOT)),
                  method=("Playwright headless Microsoft Edge, live 1920x1080 page recording of the real dashboard; "
                          "ffmpeg H.264 transcode at 30 fps; no speed-up, no edited detections; caption cards are local HTML"))
    report_path = args.out_dir / f"recording_{result['stamp']}.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(dict(video=report["video"], verification=checks, blocked=len(result["blocked"])), indent=1))
    return 0 if checks["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
