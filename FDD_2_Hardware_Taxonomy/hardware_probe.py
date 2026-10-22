"""FDD-2 hardware probe: records the host and measures real detector inference on it.

python -m FDD_2_Hardware_Taxonomy.hardware_probe [--iterations 60] [--warmup 5] [--out reports/fdd2/hardware_probe.json]

Measures, per backend actually available (PyTorch FP32 .pt; OpenVINO INT8 if exported locally):
process RSS before/after model load, warmed single-image latency (batch 1, 640, local
fixtures) and peak RSS. Never downloads weights; a backend that cannot run is recorded
as not measured with its reason, never estimated.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import psutil

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = [ROOT / "tests/assets/ife_ui3_fire.png", ROOT / "tests/assets/ife_ui3_textile.png"]
ARTIFACTS = {"pytorch_fp32": ROOT / "Backend/best.pt", "onnx_fp16": ROOT / "Backend/weights/onnx_fp16/best_fp16.onnx",
             "openvino_int8_xml": ROOT / "Backend/weights/openvino_int8/model.xml",
             "openvino_int8_bin": ROOT / "Backend/weights/openvino_int8/model.bin"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def host() -> dict:
    """Hardware/OS/runtime identification of the machine running the probe."""
    vm = psutil.virtual_memory()
    info = dict(platform=platform.platform(), machine=platform.machine(), processor=platform.processor(),
                physical_cores=psutil.cpu_count(logical=False), logical_cores=psutil.cpu_count(),
                total_ram_bytes=vm.total, available_ram_bytes=vm.available, python=platform.python_version())
    freq = psutil.cpu_freq()
    info["cpu_freq_mhz_reported"] = freq.max if freq else None
    for name in ("torch", "ultralytics", "cv2", "numpy", "openvino", "onnxruntime"):
        try:
            module = __import__(name)
            info[f"{name}_version"] = getattr(module, "__version__", None) or getattr(getattr(module, "runtime", None), "get_version", lambda: None)()
        except ImportError:
            info[f"{name}_version"] = None
    try:
        import torch
        info["cuda_available"] = torch.cuda.is_available()
        info["gpu"] = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
    except ImportError:
        info["cuda_available"], info["gpu"] = None, None
    return info


def artifacts() -> dict:
    out = {}
    for name, path in ARTIFACTS.items():
        out[name] = dict(path=str(path.relative_to(ROOT)), present=path.is_file(),
                         bytes=path.stat().st_size if path.is_file() else None,
                         sha256=sha256(path) if path.is_file() else None)
    return out


def measure(name: str, load: Callable[[], Callable], iterations: int, warmup: int) -> dict:
    proc = psutil.Process()
    rss_before = proc.memory_info().rss
    started = time.perf_counter()
    try:
        infer = load()
    except Exception as exc:  # recorded, never converted into a measurement
        return dict(backend=name, measured=False, reason=f"{type(exc).__name__}: {exc}"[:300])
    load_s = time.perf_counter() - started
    rss_loaded = proc.memory_info().rss
    try:
        import cv2
    except ImportError:
        return dict(backend=name, measured=False, reason="opencv not installed: cannot read fixtures")
    frames = [cv2.imread(str(p)) for p in FIXTURES]
    if any(f is None for f in frames):
        return dict(backend=name, measured=False, reason="fixture images missing")
    for i in range(warmup):
        infer(frames[i % len(frames)])
    latencies, peak = [], proc.memory_info().rss
    cpu_start = proc.cpu_times()
    wall_start = time.perf_counter()
    for i in range(iterations):
        t0 = time.perf_counter()
        infer(frames[i % len(frames)])
        latencies.append((time.perf_counter() - t0) * 1000)
        peak = max(peak, proc.memory_info().rss)
    wall = time.perf_counter() - wall_start
    cpu_end = proc.cpu_times()
    ordered = sorted(latencies)

    def pct(q: float) -> float:
        return ordered[min(len(ordered) - 1, max(0, round(q * len(ordered)) - 1))]
    return dict(backend=name, measured=True, iterations=iterations, warmup=warmup, model_load_seconds=round(load_s, 3),
                rss_before_load_bytes=rss_before, rss_after_load_bytes=rss_loaded, model_load_rss_delta_bytes=rss_loaded - rss_before,
                peak_rss_during_inference_bytes=peak, latency_ms=dict(mean=statistics.fmean(latencies), p50=pct(.5), p95=pct(.95),
                                                                       p99=pct(.99) if iterations >= 100 else None,
                                                                       min=ordered[0], max=ordered[-1]),
                throughput_images_per_s=iterations / wall,
                process_cpu_cores_used=((cpu_end.user + cpu_end.system) - (cpu_start.user + cpu_start.system)) / wall,
                latency_definition="single image, batch 1, imgsz 640, full predict call (preprocess + inference + NMS), warm")


def pytorch_loader() -> Callable:
    from ultralytics import YOLO
    model = YOLO(str(ARTIFACTS["pytorch_fp32"]))
    return lambda frame: model.predict(frame, imgsz=640, conf=0.25, device="cpu", verbose=False)


def openvino_loader() -> Callable:
    if not ARTIFACTS["openvino_int8_xml"].is_file():
        raise FileNotFoundError("OpenVINO INT8 export not present locally")
    from ESE_CPU3_Soak_Test.engine import OpenVINODetector
    detector = OpenVINODetector()  # verifies artifact hashes and class map against the ESE-CPU1 manifest
    return lambda frame: detector.predict_batch([frame])


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=60)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--backends", default="pytorch_fp32,openvino_int8")
    parser.add_argument("--out", type=Path, default=ROOT / "reports" / "fdd2" / "hardware_probe.json")
    args = parser.parse_args(argv)
    os.environ.setdefault("YOLO_OFFLINE", "true")
    os.environ.setdefault("YOLO_AUTOINSTALL", "false")
    loaders = {"pytorch_fp32": pytorch_loader, "openvino_int8": openvino_loader}
    report = dict(task="FDD-2", measured_at=datetime.now(timezone.utc).isoformat(), host=host(), artifacts=artifacts(),
                  fixtures=[str(p.relative_to(ROOT)) for p in FIXTURES],
                  note="Measured on this host only; not a target-device benchmark. Host may be shared (see system_cpu_percent).",
                  system_cpu_percent_at_start=psutil.cpu_percent(interval=1.0), results=[])
    for name in [b.strip() for b in args.backends.split(",") if b.strip()]:
        if name not in loaders:
            report["results"].append(dict(backend=name, measured=False, reason="unknown backend"))
            continue
        print(f"measuring {name} ({args.iterations} iterations after {args.warmup} warm-up)...", flush=True)
        report["results"].append(measure(name, loaders[name], args.iterations, args.warmup))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    for r in report["results"]:
        if r["measured"]:
            lat = r["latency_ms"]
            print(f"{r['backend']}: p50 {lat['p50']:.1f} ms, p95 {lat['p95']:.1f} ms, {r['throughput_images_per_s']:.2f} img/s, "
                  f"load +{r['model_load_rss_delta_bytes'] / 1e6:.0f} MB RSS, peak {r['peak_rss_during_inference_bytes'] / 1e6:.0f} MB")
        else:
            print(f"{r['backend']}: NOT MEASURED ({r['reason']})")
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
