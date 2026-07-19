"""Camera capture for the UGREEN FineCam Lite 4K inside the photo box.

Key points:
- 4K over USB requires MJPG fourcc, otherwise most UVC cams silently fall
  back to low resolution.
- Autofocus MUST be disabled and a fixed focus value set; otherwise the
  px->mm scale drifts between shots and geometry measurements are useless.
- Exposure and white balance SHOULD be locked too (config: camera.lock_exposure
  / lock_white_balance). Constant box lighting does NOT keep the camera response
  constant: the sensor's auto-gain reacts to scene content, so an empty (dark)
  box and a shiny object are captured at different brightness. Background
  subtraction then measures the auto-gain reaction instead of the object. After
  locking (or changing) exposure/WB the background reference MUST be recaptured.
- Not every UVC camera honours these properties; open() reads the values back
  and warns when a requested lock did not take effect.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2
import numpy as np


class CameraError(RuntimeError):
    pass


def capture_backend(camera_cfg: dict | None = None) -> int:
    """Plattformrichtiges OpenCV-Capture-Backend (einzige plattformabhängige
    Stelle neben dem Fokus-Lock): Windows braucht DSHOW für MJPG-4K + UVC-
    Properties, macOS AVFoundation, Linux V4L2. Per camera.backend in der
    Config überschreibbar (Name eines cv2.CAP_*-Attributs, z.B. "CAP_DSHOW")."""
    if camera_cfg and camera_cfg.get("backend"):
        return int(getattr(cv2, str(camera_cfg["backend"])))
    if sys.platform == "win32":
        return cv2.CAP_DSHOW
    if sys.platform == "darwin":
        return cv2.CAP_AVFOUNDATION
    return cv2.CAP_V4L2


def focus_lock_supported() -> bool:
    """CAP_PROP_AUTOFOCUS/FOCUS greifen unter Windows (DSHOW) zuverlässig,
    unter macOS/AVFoundation häufig nicht. Der Messbetrieb läuft am
    Windows-PC; auf dem Mac zeigt die UI eine Warnung statt zu crashen."""
    return sys.platform == "win32"


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
        cap = cv2.VideoCapture(self.cfg["index"], capture_backend(self.cfg))
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
        self.focus_locked = True
        if not self.cfg.get("autofocus", False):
            self.focus_locked = self._lock_focus(cap)

        self._lock_exposure_wb(cap)

        actual_w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        actual_h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        if (actual_w, actual_h) != (self.cfg["width"], self.cfg["height"]):
            print(f"[camera] WARNING: requested {self.cfg['width']}x{self.cfg['height']}, "
                  f"got {int(actual_w)}x{int(actual_h)}. Calibration is resolution-"
                  f"specific – recalibrate if this changes.")

        self._cap = cap
        self._warmup()

    def _lock_focus(self, cap: cv2.VideoCapture) -> bool:
        """AUTOFOCUS=0 + fester FOCUS-Wert setzen und ZURÜCKLESEN. Liefert
        False, wenn das Backend die Properties ignoriert (typisch macOS/
        AVFoundation) – Aufrufer zeigen dann eine Warnung: Messbetrieb ist
        nur mit Fokus-Lock verlässlich (Windows/DSHOW). Kein Crash."""
        ok_af = cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
        focus = float(self.cfg.get("focus_value", 30))
        ok_f = cap.set(cv2.CAP_PROP_FOCUS, focus)
        af_read = cap.get(cv2.CAP_PROP_AUTOFOCUS)
        locked = bool(ok_af and ok_f) and af_read == 0
        if not locked:
            print("[camera] WARNING: Fokus-Lock nicht verfügbar (Backend "
                  "ignoriert AUTOFOCUS/FOCUS) – Messbetrieb nur unter "
                  "Windows/DSHOW verlässlich.")
        return locked

    def _lock_exposure_wb(self, cap: cv2.VideoCapture) -> None:
        """Optionally pin auto-exposure/gain and auto-white-balance so the
        empty-box background and the object frame share the same camera
        response (required for valid background subtraction). No-op unless
        camera.lock_exposure / lock_white_balance are true, so absent config
        keys reproduce the previous focus-only behaviour."""
        checks: list[tuple[str, int, float]] = []  # (label, prop, requested)

        if self.cfg.get("lock_exposure", False):
            # Order matters: switch to manual BEFORE writing the exposure value,
            # otherwise many UVC drivers ignore it. 0.25 = manual, 0.75 = auto
            # on most DSHOW/UVC cams (not 0/1) -> keep it configurable.
            manual = float(self.cfg.get("auto_exposure_manual_value", 0.25))
            cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, manual)
            cap.read()  # throwaway grab so the mode switch takes effect
            checks.append(("auto_exposure", cv2.CAP_PROP_AUTO_EXPOSURE, manual))
            if "exposure" in self.cfg:
                exp = float(self.cfg["exposure"])
                cap.set(cv2.CAP_PROP_EXPOSURE, exp)
                checks.append(("exposure", cv2.CAP_PROP_EXPOSURE, exp))
            if "gain" in self.cfg:
                gain = float(self.cfg["gain"])
                cap.set(cv2.CAP_PROP_GAIN, gain)
                checks.append(("gain", cv2.CAP_PROP_GAIN, gain))

        if self.cfg.get("lock_white_balance", False):
            cap.set(cv2.CAP_PROP_AUTO_WB, 0.0)
            checks.append(("auto_wb", cv2.CAP_PROP_AUTO_WB, 0.0))
            if "wb_temperature" in self.cfg:
                wb = float(self.cfg["wb_temperature"])
                cap.set(cv2.CAP_PROP_WB_TEMPERATURE, wb)
                checks.append(("wb_temperature", cv2.CAP_PROP_WB_TEMPERATURE, wb))

        for label, prop, requested in checks:
            actual = cap.get(prop)
            if abs(actual - requested) > max(1.0, abs(requested) * 0.1):
                print(f"[camera] WARNING: {label} requested {requested}, camera "
                      f"reports {actual}. This UVC camera may ignore the property; "
                      "exposure/WB may still be automatic (recapture background "
                      "after any change, or set it via the camera's own tool).")

    def _warmup(self) -> None:
        assert self._cap is not None
        for _ in range(int(self.cfg.get("warmup_frames", 10))):
            self._cap.read()
            time.sleep(0.05)

    @property
    def capture_device(self) -> cv2.VideoCapture:
        """Direkter Gerätezugriff für Dauer-Consumer (Grab-Schleife der UI):
        dieselbe Initialisierung (4K/MJPG/Fokus-Lock) ohne Setup-Kopie.
        Raises CameraError, wenn nicht geöffnet."""
        if self._cap is None:
            raise CameraError("Camera not opened – use 'with BoxCamera(cfg) as cam:'")
        return self._cap

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
