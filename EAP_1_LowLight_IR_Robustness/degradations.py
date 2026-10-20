"""Deterministic, geometry-preserving low-light / CCTV degradations.

Every transform keeps image width, height and pixel geometry, so YOLO labels are
valid unchanged. `synthetic_ir_style` is an appearance simulation only; it is
never genuine infrared/thermal sensor data.
"""
import hashlib
import cv2
import numpy as np

TRAIN_PROFILES = ("lowlight", "uneven_illumination", "cctv_compression",
                  "motion_lowlight", "color_cast_dark", "synthetic_ir_style")
EVAL_DOMAINS = ("synthetic_lowlight", "synthetic_very_dark", "synthetic_cctv", "synthetic_ir_style")
SYNTHETIC_IR = frozenset({"synthetic_ir_style"})


def rng_for(seed, purpose, name):
    digest = hashlib.sha256(f"{seed}:{purpose}:{name}".encode()).digest()
    return np.random.default_rng(int.from_bytes(digest[:8], "little"))


def luma(image):
    return float(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).mean())


def _gamma_brightness(image, gamma, gain):
    x = image.astype(np.float32) / 255.0
    return np.clip(np.power(x, gamma) * gain * 255.0, 0, 255)


def _noise(x, rng, sigma, poisson_scale=0.0):
    if poisson_scale:
        x = rng.poisson(np.clip(x, 0, 255) * poisson_scale) / poisson_scale
    return np.clip(x + rng.normal(0, sigma, x.shape), 0, 255)


def _contrast(x, factor):
    mean = x.mean()
    return np.clip((x - mean) * factor + mean, 0, 255)


def _jpeg(image, quality):
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, int(quality)])
    if not ok:
        raise ValueError("JPEG encoding failed")
    return cv2.imdecode(encoded, cv2.IMREAD_COLOR)


def _motion_blur(image, length, angle):
    kernel = np.zeros((length, length), np.float32)
    kernel[length // 2, :] = 1.0
    rotation = cv2.getRotationMatrix2D((length / 2 - 0.5, length / 2 - 0.5), angle, 1.0)
    kernel = cv2.warpAffine(kernel, rotation, (length, length))
    return cv2.filter2D(image, -1, kernel / max(kernel.sum(), 1e-6))


def _resample(image, scale):
    h, w = image.shape[:2]
    small = cv2.resize(image, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)


def _illumination_map(shape, rng, low, high):
    h, w = shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = rng.uniform(0, w), rng.uniform(0, h)
    radius = rng.uniform(0.5, 1.2) * np.hypot(w, h)
    falloff = np.clip(1 - np.hypot(xx - cx, yy - cy) / radius, 0, 1)
    return (low + (high - low) * falloff)[..., None]


def _ir_style(image, rng, gain, noise_sigma):
    b, g, r = cv2.split(image.astype(np.float32))
    gray = np.clip(0.6 * r + 0.3 * g + 0.1 * b, 0, 255).astype(np.uint8)
    gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray).astype(np.float32)
    gray = _noise(gray * gain, rng, noise_sigma)
    gray = cv2.GaussianBlur(gray.astype(np.uint8), (3, 3), 0)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def apply(image, profile, rng):
    """Return (degraded uint8 BGR image, parameters actually used)."""
    if image is None or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("Expected a decoded 3-channel BGR image")
    if profile == "lowlight":
        p = dict(gamma=rng.uniform(1.6, 2.6), gain=rng.uniform(0.3, 0.6), sigma=rng.uniform(3, 10))
        out = _noise(_gamma_brightness(image, p["gamma"], p["gain"]), rng, p["sigma"], 0.5)
    elif profile == "uneven_illumination":
        p = dict(gamma=rng.uniform(1.2, 2.0), low=rng.uniform(0.15, 0.4), high=rng.uniform(0.8, 1.1))
        out = _gamma_brightness(image, p["gamma"], 1.0) * _illumination_map(image.shape, rng, p["low"], p["high"])
        out = _noise(out, rng, 4)
    elif profile == "cctv_compression":
        p = dict(scale=rng.uniform(0.45, 0.7), quality=int(rng.integers(15, 36)), contrast=rng.uniform(0.6, 0.85),
                 gain=rng.uniform(0.5, 0.85), sigma=rng.uniform(3, 8))
        out = _noise(_contrast(_gamma_brightness(image, 1.2, p["gain"]), p["contrast"]), rng, p["sigma"])
        out = _jpeg(_resample(out.astype(np.uint8), p["scale"]), p["quality"])
    elif profile == "motion_lowlight":
        p = dict(length=int(rng.integers(2, 6)) * 2 + 1, angle=rng.uniform(0, 180), gamma=rng.uniform(1.3, 2.0),
                 gain=rng.uniform(0.45, 0.75))
        out = _gamma_brightness(_motion_blur(image, p["length"], p["angle"]), p["gamma"], p["gain"])
        out = _noise(out, rng, 5)
    elif profile == "color_cast_dark":
        p = dict(cast=rng.uniform(0.7, 1.25, 3).round(4).tolist(), gamma=rng.uniform(1.4, 2.2), gain=rng.uniform(0.35, 0.65))
        out = _gamma_brightness(image, p["gamma"], p["gain"]) * np.array(p["cast"], np.float32)
        out = _noise(out, rng, 6)
    elif profile == "synthetic_ir_style":
        p = dict(gain=rng.uniform(0.6, 1.0), sigma=rng.uniform(4, 10))
        out = _ir_style(image, rng, p["gain"], p["sigma"])
    # Fixed-strength evaluation domains (only noise draws vary per image).
    elif profile == "synthetic_lowlight":
        p = dict(gamma=2.2, gain=0.45, sigma=6.0)
        out = _noise(_gamma_brightness(image, p["gamma"], p["gain"]), rng, p["sigma"], 0.5)
    elif profile == "synthetic_very_dark":
        p = dict(gamma=2.8, gain=0.22, contrast=0.6, sigma=9.0)
        out = _noise(_contrast(_gamma_brightness(image, p["gamma"], p["gain"]), p["contrast"]), rng, p["sigma"], 0.5)
    elif profile == "synthetic_cctv":
        p = dict(gain=0.6, contrast=0.7, length=7, angle=0.0, scale=0.5, quality=20, sigma=5.0)
        out = _contrast(_gamma_brightness(_motion_blur(image, p["length"], p["angle"]), 1.3, p["gain"]), p["contrast"])
        out = _jpeg(_resample(_noise(out, rng, p["sigma"]).astype(np.uint8), p["scale"]), p["quality"])
    else:
        raise ValueError(f"Unknown degradation profile: {profile}")
    out = np.clip(out, 0, 255).astype(np.uint8)
    assert out.shape == image.shape, "degradation changed image geometry"
    return out, {k: (round(float(v), 4) if isinstance(v, (float, np.floating)) else v) for k, v in p.items()}
