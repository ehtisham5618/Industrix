from __future__ import annotations

import time
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse


class CameraSource(Protocol):
    source_fps: float

    def open(self) -> None:
        ...

    def read(self) -> tuple[bool, Any]:
        ...

    def close(self) -> None:
        ...


class FileCameraSource:
    def __init__(self, source: str, loop: bool = True, stop_event=None, realtime: bool = True):
        self.source = source
        self.loop = loop
        self.capture: Any = None
        self.source_fps = 0.0
        self.session_generation = 0
        self.stop_event = stop_event or threading.Event()
        self.realtime = realtime
        self.is_live = urlparse(str(source)).scheme.lower() in {'rtsp','rtsps','http','https'} or str(source).isdigit()
        self.read_timeout_ms = 2000
        self.open_timeout_ms = 2000
        self.loop_rewinds = 0
        self._due = 0.0

    def open(self) -> None:
        try:
            import cv2  # type: ignore
        except ImportError as exc:
            raise RuntimeError("opencv-python is required for file camera sources.") from exc
        self.close()
        if self.is_live and not str(self.source).isdigit():
            # Open-only timeout properties are supported by FFmpeg/GStreamer.
            # Fail explicitly if unsupported; never fall back to unbounded reads.
            self.capture = cv2.VideoCapture(self.source, cv2.CAP_FFMPEG,
                [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,self.open_timeout_ms,
                 cv2.CAP_PROP_READ_TIMEOUT_MSEC,self.read_timeout_ms])
        elif str(self.source).isdigit():
            self.capture = cv2.VideoCapture(int(self.source))
        else:
            path = Path(self.source)
            if not path.exists():
                raise FileNotFoundError('Configured local camera file does not exist')
            self.capture = cv2.VideoCapture(str(path))
        if not self.capture.isOpened():
            self.close()
            raise RuntimeError('Unable to open configured camera source')
        fps = float(self.capture.get(cv2.CAP_PROP_FPS) or 0.0)
        self.source_fps = fps if fps > 0 else 30.0
        self._due = time.perf_counter()

    def read(self) -> tuple[bool, Any]:
        if self.capture is None:
            raise RuntimeError("Camera source has not been opened.")
        if not self.is_live and self.realtime:
            if self.stop_event.wait(max(0,self._due-time.perf_counter())):
                return False,None
            self._due += 1/self.source_fps
        ok, frame = self.capture.read()
        if ok:
            return True, frame
        if not self.loop or self.is_live or self.stop_event.is_set():
            return False, None
        self.capture.set(1, 0)
        self.session_generation += 1
        self.loop_rewinds += 1
        return self.capture.read()

    def close(self) -> None:
        if self.capture is not None:
            self.capture.release()
            self.capture = None


@dataclass
class SyntheticCameraSource:
    width: int = 640
    height: int = 360
    source_fps: float = 30.0
    max_frames: int | None = None
    fail_after: int | None = None

    def __post_init__(self) -> None:
        self._frame = 0

    def open(self) -> None:
        self._frame = 0

    def read(self) -> tuple[bool, dict[str, int]]:
        if self.fail_after is not None and self._frame >= self.fail_after:
            return False, {}
        if self.max_frames is not None and self._frame >= self.max_frames:
            return False, {}
        self._frame += 1
        time.sleep(1.0 / max(1.0, self.source_fps))
        return True, {"width": self.width, "height": self.height, "synthetic_frame_id": self._frame}

    def close(self) -> None:
        pass


