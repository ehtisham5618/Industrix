"""EAP-3 image-size gate.

Primary measurement: the unpacked image filesystem, `du -sxb /` in a fresh
container started with --network none (the container's writable layer is empty,
so this is exactly the image content; hard links counted once). `docker image
inspect .Size` is recorded too but is NOT the gate: with the containerd image
store (Docker Desktop default) it reports compressed content (~= gzip size),
and `docker image ls` "disk usage" adds compressed blobs to unpacked snapshots.
Limit: < 1.8 GB decimal = 1 800 000 000 bytes (stricter than 1.8 GiB).
Exit 1 when the image is too large, 2 when it cannot be measured.

python EAP_3_Lightweight_Docker/check_image_size.py industrix:eap3 [--compressed] [--out report.json]
"""
import argparse
import gzip
import json
import subprocess
import sys
from pathlib import Path

LIMIT_BYTES = 1_800_000_000


def docker(*args, **kwargs):
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=True, **kwargs).stdout.strip()


def inspect_size(image):
    raw = docker("image", "inspect", image, "--format", "{{.Size}}")
    if not raw.isdigit():
        raise ValueError(f"Non-numeric size from docker image inspect: {raw!r}")
    return int(raw)


def unpacked_size(image):
    raw = docker("run", "--rm", "--network", "none", "--user", "0", "--entrypoint", "du", image, "-sxb", "/", timeout=300)
    value = raw.split()[0] if raw else ""
    if not value.isdigit():
        raise ValueError(f"Non-numeric du output: {raw!r}")
    return int(value)


def image_store():
    return docker("info", "--format", "{{json .DriverStatus}}")


def compressed_size(image):
    """gzip(-6) of `docker save`; approximates registry transfer size, not the gate."""
    process = subprocess.Popen(["docker", "save", image], stdout=subprocess.PIPE)
    counter = _Counter()
    with gzip.GzipFile(fileobj=counter, mode="wb", compresslevel=6) as stream:
        for block in iter(lambda: process.stdout.read(1 << 20), b""):
            stream.write(block)
    if process.wait():
        raise RuntimeError("docker save failed")
    return counter.count


class _Counter:
    count = 0

    def write(self, data):
        self.count += len(data)
        return len(data)

    def flush(self):
        pass


def layers(image):
    rows = docker("history", "--no-trunc", "--format", "{{json .}}", image).splitlines()
    out = []
    for row in rows:
        item = json.loads(row)
        out.append(dict(size=item["Size"], created_by=item["CreatedBy"][:160]))
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    parser.add_argument("--limit", type=int, default=LIMIT_BYTES)
    parser.add_argument("--compressed", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    try:
        size = unpacked_size(args.image)
        reported = inspect_size(args.image)
    except (subprocess.CalledProcessError, ValueError, FileNotFoundError) as exc:
        print(f"SIZE GATE: NOT VERIFIED - could not measure {args.image}: {exc}", file=sys.stderr)
        return 2
    passed = size < args.limit
    report = dict(image=args.image, image_id=docker("image", "inspect", args.image, "--format", "{{.Id}}"),
                  primary_measurement="du -sxb / in a fresh --network none container (unpacked image filesystem)",
                  uncompressed_bytes=size, docker_inspect_size_bytes=reported, image_store=image_store(), uncompressed_gb_decimal=size / 1e9, uncompressed_gib=size / 2**30,
                  limit_bytes=args.limit, limit_convention="decimal GB (1.8e9 bytes); stricter than 1.8 GiB",
                  headroom_bytes=args.limit - size, status="PASS" if passed else "FAIL", layers=layers(args.image))
    if args.compressed:
        report["compressed_gzip_bytes"] = compressed_size(args.image)
        report["compressed_note"] = "gzip -6 of docker save; informational, not the gate"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"SIZE GATE {report['status']}: {args.image} unpacked = {size} bytes ({size / 1e9:.3f} GB, {size / 2**30:.3f} GiB); "
          f"limit {args.limit} bytes; headroom {args.limit - size} bytes")
    print(f"docker image inspect .Size = {reported} bytes (store-dependent; compressed on containerd; not the gate)")
    if "compressed_gzip_bytes" in report:
        print(f"compressed (gzip docker save): {report['compressed_gzip_bytes']} bytes")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
