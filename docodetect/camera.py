"""Camera capture for the UGREEN FineCam Lite 4K inside the photo box.

Key points:
- 4K over USB requires MJPG fourcc, otherwise most UVC cams silently fall
  back to low resolution.
- Autofocus MUST be disabled and a fixed focus value set; otherwise the
  px->mm scale drifts between shots and geometry measurements are useless.
- A few warmup frames are discarded so auto-exposure settles (exposure/WB
  can stay automatic since the box lighting is constant; lock them too if
  color features turn out noisy).
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np


class CameraError(RuntimeError):
    pass


class BoxCamera:
    def __init__(self, cfg: dict):
        self.cfg = cfg["camera"]
        self._cap: cv2.VideoCapture | None = None

    def __enter__(self) -> "BoxCamera":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def open(self) -> None:
        cap = cv2.VideoCapture(self.cfg["index"])
        if not cap.isOpened():
            raise CameraError(
                f"Cannot open camera index {self.cfg['index']}. "
                "Check USB connection / device index."
            )

        fourcc = cv2.VideoWriter_fourcc(*self.cfg.get("fourcc", "MJPG"))
        cap.set(cv2.CAP_PROP_FOURCC, fourcc)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.cfg["width"])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.cfg["height"])

        # Lock focus. Some backends need AUTOFOCUS=0 before FOCUS is writable.
        if not self.cfg.get("autofocus", False):
            cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
            cap.set(cv2.CAP_PROP_FOCUS, float(self.cfg.get("focus_value", 30)))

        actual_w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        actual_h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        if (actual_w, actual_h) != (self.cfg["width"], self.cfg["height"]):
            print(f"[camera] WARNING: requested {self.cfg['width']}x{self.cfg['height']}, "
                  f"got {int(actual_w)}x{int(actual_h)}. Calibration is resolution-"
                  f"specific – recalibrate if this changes.")

        self._cap = cap
        self._warmup()

    def _warmup(self) -> None:
        assert self._cap is not None
        for _ in range(int(self.cfg.get("warmup_frames", 10))):
            self._cap.read()
            time.sleep(0.05)

    def capture(self) -> np.ndarray:
        """Grab a single BGR frame."""
        if self._cap is None:
            raise CameraError("Camera not opened – use 'with BoxCamera(cfg) as cam:'")
        # Flush stale frames from the driver buffer, then grab a fresh one.
        for _ in range(3):
            self._cap.grab()
        ok, frame = self._cap.read()
        if not ok or frame is None:
            raise CameraError("Frame capture failed.")
        return frame

    def capture_to_file(self, path: str | Path) -> Path:
        frame = self.capture()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(path), frame):
            raise CameraError(f"Could not write image to {path}")
        return path

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None


def load_image(path: str | Path) -> np.ndarray:
    """Load an image from disk (for offline/testing use instead of the camera)."""
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"Cannot read image: {path}")
    return img
